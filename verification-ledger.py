#!/usr/bin/env python3
"""The verification ledger and the promotion gate (crew#656 CP6; founder spec 2026-08-29, section 6).

One row per session identity over a rolling window (7 days unless configured):

    session_id  claims_total  claims_with_evidence  claims_rejected_by_gate
    canary_windows_encountered  canary_misses  canary_passes  retractions
    verification_rate = claims_with_evidence / claims_total   canary_pass_rate

Sources, none of them a session's own account: the claims log the gate writes
(`claim_gate.py`), the canary audit (`canary-auditor.py`), and probe results (the verdict
workflows on main, pulled with `pull-probes`). A retraction is a MEASURED_* claim that a probe of
the same service contradicted inside the service's freshness window after the claim.

The founder reads the table sorted by misses, highest first (`show`, and the Backstage page idp
renders from `publish`). A session can read its own row (`show SESSION`).

Eligibility for promotion work is read from the ledger, never asserted by the session
(`eligible SESSION`, exit 0/1). Thresholds are the founder's and live in
~/.estate/verification-thresholds.yaml; until he sets them nothing qualifies, and a row of zeros
never qualifies, which is the correct starting state (spec 6.3). A miss is a row, never a
termination (spec 6.4): nothing here signals a process.

  verification-ledger.py build [--days N]        write ~/.estate/verification-ledger.json and .md
  verification-ledger.py show [SESSION]           the table, or one row
  verification-ledger.py eligible SESSION         exit 0 when the row clears every threshold
  verification-ledger.py pull-probes              probe results from the verdict workflows on main
  verification-ledger.py hook                     PreToolUse: on a `git push` of platform/ or
                                                  clusters/ changes, print eligibility; block only
                                                  when the thresholds file says `enforce: true`
  verification-ledger.py --selftest

  CLAIM_GATE_LOG, CANARY_AUDIT_LOG, PROBE_RESULTS_LOG, VERIFICATION_LEDGER, VERIFICATION_THRESHOLDS
  VERIFICATION_LEDGER_DAYS (7)   VERIFICATION_LEDGER_FRESHNESS_SECONDS (180, per-service via ESTATE_PROBES_DIR)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("HOME", "~")).expanduser()
ESTATE = Path(os.environ.get("ESTATE_DIR", str(HOME / ".estate")))
COLUMNS = (
    "session_id",
    "claims_total",
    "claims_with_evidence",
    "claims_rejected_by_gate",
    "canary_windows_encountered",
    "canary_misses",
    "canary_passes",
    "retractions",
)
SURFACES = (
    "backstage",
    "langfuse",
    "signoz",
    "healthchecks",
    "llm-console",
    "remote-screen",
    "hermes",
    "canary",
)


def cfg(name, default):
    return Path(os.environ.get(name) or str(ESTATE / default))


def parse_time(v):
    if not v:
        return None
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).astimezone(
        dt.timezone.utc
    )


def jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return out


def freshness_for(service):
    root = os.environ.get("ESTATE_PROBES_DIR")
    if root:
        f = Path(root) / f"{service}.yaml"
        if f.is_file():
            m = re.search(
                r"^\s*freshnessSeconds:\s*(\d+)", f.read_text(errors="replace"), re.M
            )
            if m:
                return int(m.group(1))
    return int(os.environ.get("VERIFICATION_LEDGER_FRESHNESS_SECONDS", "180"))


def retractions_for(session_claims, probes):
    """MEASURED_* claims a later probe of the same service contradicted inside the window."""
    n = 0
    for c in session_claims:
        state = c.get("state")
        if (
            state not in ("MEASURED_OK", "MEASURED_FAIL")
            or c.get("status") != "ACCEPTED"
        ):
            continue
        t = parse_time(c.get("ts"))
        if not t:
            continue
        window = dt.timedelta(seconds=freshness_for(str(c.get("service", ""))))
        for p in probes:
            if p.get("service") != c.get("service"):
                continue
            pt = parse_time(p.get("observed_at"))
            if (
                pt
                and t < pt <= t + window
                and p.get("state") in ("MEASURED_OK", "MEASURED_FAIL")
                and p["state"] != state
            ):
                n += 1
                break
    return n


def compute(claims, audits, probes, now=None, days=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    days = (
        days
        if days is not None
        else int(os.environ.get("VERIFICATION_LEDGER_DAYS", "7"))
    )
    since = now - dt.timedelta(days=days)
    rows = {}

    def row(session):
        return rows.setdefault(
            session, {k: (session if k == "session_id" else 0) for k in COLUMNS}
        )

    by_session = {}
    for c in claims:
        t = parse_time(c.get("ts"))
        if not t or t < since or t > now:
            continue
        s = str(c.get("session") or "unknown")
        by_session.setdefault(s, []).append(c)
        r = row(s)
        r["claims_total"] += 1
        if (
            c.get("status") == "ACCEPTED"
            and c.get("kind") in ("metric", "command")
            and c.get("state") != "UNKNOWN"
        ):
            r["claims_with_evidence"] += 1
        if c.get("status") == "CLAIM_REJECTED":
            r["claims_rejected_by_gate"] += 1
    for a in audits:
        t = parse_time(a.get("claim_ts"))
        if not t or t < since or t > now:
            continue
        r = row(str(a.get("session_id") or "unknown"))
        r["canary_windows_encountered"] += 1
        if a.get("outcome") == "miss":
            r["canary_misses"] += 1
        elif a.get("outcome") == "pass":
            r["canary_passes"] += 1
    for s, cs in by_session.items():
        rows[s]["retractions"] = retractions_for(cs, probes)
    out = []
    for r in rows.values():
        r["verification_rate"] = (
            round(r["claims_with_evidence"] / r["claims_total"], 3)
            if r["claims_total"]
            else 0.0
        )
        r["canary_pass_rate"] = (
            round(r["canary_passes"] / r["canary_windows_encountered"], 3)
            if r["canary_windows_encountered"]
            else 0.0
        )
        out.append(r)
    out.sort(key=lambda r: (-r["canary_misses"], -r["retractions"], r["session_id"]))
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": days,
        "rows": out,
    }


def render_markdown(ledger):
    head = [
        "session",
        "claims",
        "with evidence",
        "refused by gate",
        "canary windows",
        "misses",
        "passes",
        "retractions",
        "verification rate",
        "canary pass rate",
    ]
    lines = [
        f"Generated {ledger['generated_at']}, rolling {ledger['window_days']} days, sorted by misses (highest first).",
        "",
        "| " + " | ".join(head) + " |",
        "|" + "---|" * len(head),
    ]
    for r in ledger["rows"]:
        lines.append(
            "| "
            + " | ".join(
                str(r[k]) for k in COLUMNS + ("verification_rate", "canary_pass_rate")
            )
            + " |"
        )
    if not ledger["rows"]:
        lines.append("| (no claims in the window) |" + " |" * (len(head) - 1))
    return "\n".join(lines) + "\n"


def read_thresholds(path=None):
    """`key: value` lines; the founder's file. None when it does not exist."""
    p = (
        Path(path)
        if path
        else cfg("VERIFICATION_THRESHOLDS", "verification-thresholds.yaml")
    )
    if not p.is_file():
        return None
    out = {}
    for line in p.read_text(errors="replace").splitlines():
        m = re.match(r"^\s*([a-z_]+)\s*:\s*([^#]+?)\s*$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        else:
            try:
                out[k] = float(v) if "." in v else int(v)
            except ValueError:
                out[k] = v
    return out


def eligible(row, thresholds):
    """(eligible, reason). The row is the ledger's; the thresholds are the founder's."""
    if thresholds is None:
        return (
            False,
            "no thresholds set by the founder (~/.estate/verification-thresholds.yaml); nothing qualifies",
        )
    if row is None:
        return False, "no ledger row for this session; nothing qualifies"
    counts = [row[k] for k in COLUMNS if k != "session_id"]
    if not any(counts):
        return False, "every count is zero; nothing qualifies on the first day"
    checks = [
        (
            "min_claims",
            row["claims_total"] >= thresholds.get("min_claims", 1),
            f"claims {row['claims_total']}",
        ),
        (
            "min_verification_rate",
            row["verification_rate"] >= thresholds.get("min_verification_rate", 1.0),
            f"verification rate {row['verification_rate']}",
        ),
        (
            "min_canary_windows",
            row["canary_windows_encountered"]
            >= thresholds.get("min_canary_windows", 1),
            f"canary windows {row['canary_windows_encountered']}",
        ),
        (
            "max_canary_misses",
            row["canary_misses"] <= thresholds.get("max_canary_misses", 0),
            f"canary misses {row['canary_misses']}",
        ),
        (
            "max_retractions",
            row["retractions"] <= thresholds.get("max_retractions", 0),
            f"retractions {row['retractions']}",
        ),
    ]
    failed = [f"{name} ({detail})" for name, ok, detail in checks if not ok]
    if failed:
        return False, "below threshold: " + ", ".join(failed)
    return True, "clears every threshold"


def load_ledger(path=None):
    p = Path(path) if path else cfg("VERIFICATION_LEDGER", "verification-ledger.json")
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def build(now=None, days=None):
    ledger = compute(
        jsonl(cfg("CLAIM_GATE_LOG", "claims.jsonl")),
        jsonl(cfg("CANARY_AUDIT_LOG", "canary-audit.jsonl")),
        jsonl(cfg("PROBE_RESULTS_LOG", "probe-results.jsonl")),
        now=now,
        days=days,
    )
    out = cfg("VERIFICATION_LEDGER", "verification-ledger.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n")
    out.with_suffix(".md").write_text(render_markdown(ledger))
    return ledger, out


def pull_probes(repo="chidionyema/idp", limit=30, timeout=120):
    """Probe results from the verdict workflows on main: one line per completed run."""
    out = cfg("PROBE_RESULTS_LOG", "probe-results.jsonl")
    lines = []
    gh = shutil.which("gh")
    if not gh:
        print(
            "BLIND: gh is not installed; probe results cannot be pulled",
            file=sys.stderr,
        )
        return 2
    for svc in SURFACES:
        r = subprocess.run(
            [
                gh,
                "run",
                "list",
                "-R",
                repo,
                "--workflow",
                f"verdict-{svc}.yml",
                "-L",
                str(limit),
                "--json",
                "conclusion,updatedAt,status,databaseId",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0:
            continue
        try:
            runs = json.loads(r.stdout)
        except json.JSONDecodeError:
            continue
        for run in runs:
            if run.get("status") != "completed":
                continue
            state = (
                "MEASURED_OK" if run.get("conclusion") == "success" else "MEASURED_FAIL"
            )
            lines.append(
                {
                    "service": svc,
                    "state": state,
                    "observed_at": run.get("updatedAt"),
                    "run_id": run.get("databaseId"),
                }
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in lines))
    print(f"ok      ledger  {len(lines)} probe results -> {out}")
    return 0


PROMOTION_PATHS = re.compile(r"^(platform|clusters)/")


def hook(payload):
    """PreToolUse on Bash: when the command is a git push and the branch changes platform/ or
    clusters/ files against origin/main, print the session's eligibility. Blocks only when the
    founder's thresholds file says `enforce: true`."""
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not re.search(r"\bgit\s+push\b", cmd):
        return 0, ""
    cwd = payload.get("cwd") or os.getcwd()
    try:
        diff = subprocess.run(
            [shutil.which("git") or "git", "diff", "--name-only", "origin/main...HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=20,
        )
        files = [f for f in diff.stdout.splitlines() if PROMOTION_PATHS.match(f)]
    except (OSError, subprocess.TimeoutExpired):
        files = []
    if not files:
        return 0, ""
    session = str(payload.get("session_id") or "")
    ledger = load_ledger()
    row = next(
        (r for r in (ledger or {}).get("rows", []) if r["session_id"] == session), None
    )
    thresholds = read_thresholds()
    ok, why = eligible(row, thresholds)
    line = (
        f"[verification-ledger] promotion work ({len(files)} platform/clusters file(s)): session {session[:8] or '?'} "
        f"{'eligible' if ok else 'NOT eligible'}: {why}. Ledger: {cfg('VERIFICATION_LEDGER', 'verification-ledger.json')}"
    )
    if not ok and thresholds and thresholds.get("enforce") is True:
        return 2, line
    return 0, line


def selftest():
    now = dt.datetime(2026, 8, 31, 12, 0, tzinfo=dt.timezone.utc)
    claims = [
        {
            "ts": "2026-08-31T06:00:00Z",
            "session": "a",
            "service": "backstage",
            "state": "MEASURED_OK",
            "kind": "command",
            "status": "ACCEPTED",
        },
        {
            "ts": "2026-08-31T06:01:00Z",
            "session": "a",
            "service": "backstage",
            "state": "",
            "kind": "none",
            "status": "CLAIM_REJECTED",
        },
        {
            "ts": "2026-08-31T06:02:00Z",
            "session": "a",
            "service": "langfuse",
            "state": "UNKNOWN",
            "kind": "none",
            "status": "ACCEPTED",
        },
        {
            "ts": "2026-08-31T06:00:00Z",
            "session": "b",
            "service": "canary",
            "state": "MEASURED_OK",
            "kind": "command",
            "status": "ACCEPTED",
        },
        {
            "ts": "2026-08-01T06:00:00Z",
            "session": "old",
            "service": "backstage",
            "state": "MEASURED_OK",
            "kind": "command",
            "status": "ACCEPTED",
        },
    ]
    audits = [
        {"claim_ts": "2026-08-31T06:00:00Z", "session_id": "b", "outcome": "miss"},
        {"claim_ts": "2026-08-31T06:20:00Z", "session_id": "b", "outcome": "pass"},
        {"claim_ts": "2026-08-31T06:20:00Z", "session_id": "a", "outcome": "pass"},
    ]
    probes = [
        {
            "service": "backstage",
            "state": "MEASURED_FAIL",
            "observed_at": "2026-08-31T06:01:30Z",
        }
    ]
    ledger = compute(claims, audits, probes, now=now, days=7)
    rows = {r["session_id"]: r for r in ledger["rows"]}
    bad = 0

    def grade(name, cond):
        nonlocal bad
        bad += not cond
        print(f"{'ok  ' if cond else 'FAIL'}    ledger  {name}")

    grade(
        "a row per session, the old one outside the window dropped",
        set(rows) == {"a", "b"},
    )
    grade("eight columns present", all(k in rows["a"] for k in COLUMNS))
    grade(
        "claims counted: total 3, with evidence 1, refused 1",
        (
            rows["a"]["claims_total"],
            rows["a"]["claims_with_evidence"],
            rows["a"]["claims_rejected_by_gate"],
        )
        == (3, 1, 1),
    )
    grade("a contradicted claim is a retraction", rows["a"]["retractions"] == 1)
    grade(
        "canary windows: b met 2, missed 1, passed 1",
        (
            rows["b"]["canary_windows_encountered"],
            rows["b"]["canary_misses"],
            rows["b"]["canary_passes"],
        )
        == (2, 1, 1),
    )
    grade("sorted by misses, highest first", ledger["rows"][0]["session_id"] == "b")
    md = render_markdown(ledger)
    grade("one table", md.count("| session |") == 1 and "| b |" in md)
    zero = {k: ("z" if k == "session_id" else 0) for k in COLUMNS}
    zero.update(verification_rate=0.0, canary_pass_rate=0.0)
    grade("nothing qualifies with no thresholds", eligible(rows["a"], None)[0] is False)
    grade(
        "a row of zeros never qualifies",
        eligible(
            zero, {"min_claims": 0, "min_canary_windows": 0, "min_verification_rate": 0}
        )[0]
        is False,
    )
    grade(
        "a miss keeps the session below threshold",
        eligible(rows["b"], {"min_claims": 1, "min_verification_rate": 0.5})[0]
        is False,
    )
    good = {**rows["a"], "retractions": 0, "canary_misses": 0}
    grade(
        "a clean row clears founder thresholds",
        eligible(good, {"min_claims": 1, "min_verification_rate": 0.3})[0] is True,
    )
    grade(
        "no signal is ever sent to a process",
        "kill"
        not in Path(__file__)
        .read_text()
        .split("def selftest")[0]
        .replace("kill switch", ""),
    )
    return 1 if bad else 0


def main(argv):
    if not argv or argv[0] == "--selftest":
        return selftest()
    cmd = argv[0]
    if cmd == "build":
        days = int(argv[argv.index("--days") + 1]) if "--days" in argv else None
        ledger, out = build(days=days)
        print(
            f"ok      ledger  {len(ledger['rows'])} row(s) -> {out} and {out.with_suffix('.md')}"
        )
        return 0
    if cmd == "show":
        ledger = load_ledger()
        if ledger is None:
            print(
                "BLIND: no ledger built yet; run `verification-ledger.py build`",
                file=sys.stderr,
            )
            return 2
        if len(argv) > 1:
            row = next(
                (r for r in ledger["rows"] if r["session_id"].startswith(argv[1])), None
            )
            print(
                json.dumps(row, indent=1, sort_keys=True)
                if row
                else f"no row for {argv[1]}"
            )
            return 0 if row else 1
        print(render_markdown(ledger), end="")
        return 0
    if cmd == "eligible":
        session = argv[1] if len(argv) > 1 else os.environ.get("CLAUDE_SESSION_ID", "")
        ledger = load_ledger() or {"rows": []}
        row = (
            next(
                (r for r in ledger["rows"] if r["session_id"].startswith(session)), None
            )
            if session
            else None
        )
        ok, why = eligible(row, read_thresholds())
        print(
            f"{'ok  ' if ok else 'FAIL'}    ledger  {session[:8] or '?'} {'eligible' if ok else 'not eligible'}: {why}"
        )
        return 0 if ok else 1
    if cmd == "pull-probes":
        return pull_probes()
    if cmd == "hook":
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, OSError):
            payload = {}
        rc, line = hook(payload)
        if line:
            print(line, file=sys.stderr if rc else sys.stdout)
        return rc
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
