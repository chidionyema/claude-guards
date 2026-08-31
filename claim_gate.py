#!/usr/bin/env python3
"""The claim envelope and its gate (crew#656 CP2; founder spec 2026-08-29 22:13Z, section 4).

A claim about live state is a small JSON record, not a sentence. It carries the service, one of
the three states (`state_vocabulary.py`) and the evidence that produced it. The gate reads the
record before the post is written: on the board (`estate-broadcast.py`), on the feed
(`feed-guard.py`) and in a reply to the founder (`dod-guard.py`). Prevention at the write beats
judgement at the read.

The envelope, from the spec, section 4.1:

    ```claim
    {"claim": "backstage catalogue is reachable post-auth",
     "state": "MEASURED_OK",
     "service": "backstage",
     "evidence": {"kind": "metric",
                  "query": "probe_state{service=\\"backstage\\"}",
                  "value": 1,
                  "observed_at": "2026-08-29T21:24:11Z",
                  "age_seconds": 42,
                  "run_id": "bk-2026-08-29-2124-01"}}
    ```

It rides inside any text as a fenced block tagged `claim`. A text that carries the words
MEASURED_OK or MEASURED_FAIL and no such block is refused: those two words are the only ones that
assert a measurement, so a measurement without its record is exactly the thing being stopped.

The rejection table (section 4.2) is `validate()`. Two outcomes are kept apart on purpose:
`CLAIM_REJECTED` is content the gate read and refused; `GATE_UNAVAILABLE` is the gate unable to
read (no metric store reachable). Both stop the write; only the first is the author's fault, and
the second is written to the claims log so a channel that does not need the metric store (a
`command` or `none` claim, the feed, the board) can carry the news that the gate is broken.

Configuration, never constants (founder 2026-08-31, "configurable obvs"):
  CLAIM_GATE_FRESHNESS_SECONDS   default window when no probe definition names one (180)
  ESTATE_PROBES_DIR              directory of probe definitions; `<service>.yaml` may carry
                                 `freshnessSeconds: N`
  ESTATE_PROMETHEUS_URL          the metric store; unset means every `metric` claim is
                                 GATE_UNAVAILABLE, never silently accepted
  CLAIM_GATE_LOG                 the claims log the ledger reads (~/.estate/claims.jsonl)

  claim_gate.py check [FILE|-]           gate a text or a bare envelope, exit 0/1/2
  claim_gate.py new --service S --state MEASURED_OK --claim "..." --command "kubectl get ..."
                                         run the command and print the finished block
  claim_gate.py --selftest
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from state_vocabulary import PERMITTED_STATES, Refusal, check as vocabulary_check  # noqa: E402

HOME = Path(os.environ.get("HOME", "~")).expanduser()
ESTATE = Path(os.environ.get("ESTATE_DIR", str(HOME / ".estate")))
CLAIMS_LOG = Path(os.environ.get("CLAIM_GATE_LOG", str(ESTATE / "claims.jsonl")))
DEFAULT_FRESHNESS = int(os.environ.get("CLAIM_GATE_FRESHNESS_SECONDS", "180"))
KINDS = ("metric", "command", "none")
OUTPUT_LIMIT = 512

ACCEPTED = "ACCEPTED"
REJECTED = "CLAIM_REJECTED"
UNAVAILABLE = "GATE_UNAVAILABLE"

FENCE = re.compile(r"```claim[^\n]*\n(.*?)```", re.S)
MEASURED_WORD = re.compile(r"\bMEASURED_(?:OK|FAIL)\b")
LEAD_WORD = re.compile(r"\bLEAD\b")


class Verdict:
    """What the gate decided about one envelope."""

    def __init__(
        self, status, reason="", envelope=None, corrected_query="", warnings=None
    ):
        self.status = status
        self.reason = reason
        self.envelope = envelope
        self.corrected_query = corrected_query
        self.warnings = list(warnings or [])

    @property
    def ok(self):
        return self.status == ACCEPTED

    def text(self):
        if self.status == ACCEPTED:
            return "ACCEPTED" + ("".join("\n  warning: " + w for w in self.warnings))
        head = f"{self.status} (crew#656 CP2, founder spec section 4.2): {self.reason}"
        if self.corrected_query:
            head += f"\n  run instead: {self.corrected_query}"
        if self.status == UNAVAILABLE:
            head += (
                "\n  This is a broken gate, not a refused claim. A claim whose evidence is a "
                "`command` or whose state is UNKNOWN does not need the metric store; use one "
                "to report the gate."
            )
        return head


def parse_time(value):
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        t = dt.datetime.fromisoformat(v)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


def freshness_for(service, probes_dir=None):
    """The service's window from its probe definition, else the configured default."""
    root = probes_dir if probes_dir is not None else os.environ.get("ESTATE_PROBES_DIR")
    if root and service:
        f = Path(root) / f"{service}.yaml"
        if f.is_file():
            m = re.search(
                r"^\s*freshnessSeconds:\s*(\d+)", f.read_text(errors="replace"), re.M
            )
            if m:
                return int(m.group(1))
    return DEFAULT_FRESHNESS


def query_metric(query, url=None, timeout=5):
    """Instant query against the metric store. None = store unreachable or unset (config);
    [] = the query ran and returned no series (content)."""
    base = url if url is not None else os.environ.get("ESTATE_PROMETHEUS_URL")
    if not base:
        return None
    q = urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(  # noqa: S310 - ESTATE_PROMETHEUS_URL is the operator's own metric store
            f"{base.rstrip('/')}/api/v1/query?{q}", timeout=timeout
        ) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - any failure to reach the store is a config failure
        return None
    if body.get("status") != "success":
        return None
    return body.get("data", {}).get("result", [])


def is_lead(env):
    return bool(env.get("lead")) or bool(
        LEAD_WORD.match(str(env.get("claim", "")).strip())
    )


def validate(env, now=None, prom=None, probes_dir=None):
    """The rejection table. Returns a Verdict; never raises for content."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(env, dict):
        return Verdict(REJECTED, "the envelope is not a JSON object")
    claim = env.get("claim")
    state = env.get("state")
    service = env.get("service")
    evidence = env.get("evidence")
    if not isinstance(claim, str) or not claim.strip():
        return Verdict(REJECTED, "`claim` is missing")
    if state not in PERMITTED_STATES:
        return Verdict(
            REJECTED,
            f"`state` must be one of {', '.join(PERMITTED_STATES)}, got {state!r}",
        )
    if not isinstance(service, str) or not service.strip():
        return Verdict(REJECTED, "`service` is missing")
    if evidence is None and state == "UNKNOWN":
        evidence = {"kind": "none"}
        env = {**env, "evidence": evidence}
    if not isinstance(evidence, dict) or evidence.get("kind") not in KINDS:
        return Verdict(REJECTED, f"`evidence.kind` must be one of {', '.join(KINDS)}")
    kind = evidence["kind"]

    try:
        vocabulary_check(claim)
    except Refusal as exc:
        token = re.search(r"refused token: '([^']+)'", str(exc))
        return Verdict(
            REJECTED,
            f"banned vocabulary in the assertion: {token.group(1) if token else 'see below'}\n"
            + str(exc),
        )

    if is_lead(env):
        if state != "UNKNOWN":
            return Verdict(
                REJECTED,
                "a LEAD may not carry a measured state; a peer's word is not evidence",
            )
        if not str(env.get("source", "")).strip():
            return Verdict(
                REJECTED, "a LEAD must name its source (`source`: the peer session)"
            )
        return Verdict(ACCEPTED, envelope=env)

    if state == "UNKNOWN":
        return Verdict(ACCEPTED, envelope=env)

    # MEASURED_OK or MEASURED_FAIL from here: evidence is mandatory and is checked.
    if kind == "none":
        return Verdict(
            REJECTED,
            f"state {state} with `evidence.kind: none`; a measurement carries its evidence",
            corrected_query=f'probe_state{{service="{service}"}}',
        )

    observed = parse_time(evidence.get("observed_at"))
    age = evidence.get("age_seconds")
    if age is None and observed is not None:
        age = int((now - observed).total_seconds())
    if age is None:
        return Verdict(REJECTED, "evidence has neither `observed_at` nor `age_seconds`")
    window = freshness_for(service, probes_dir)
    warnings = []
    if age > window:
        env = {**env, "state": "UNKNOWN", "evidence": {**evidence, "age_seconds": age}}
        warnings.append(
            f"evidence is {age}s old, window for {service} is {window}s: state rewritten to UNKNOWN"
        )
        return Verdict(ACCEPTED, envelope=env, warnings=warnings)

    if evidence.get("probe_identifier_present") == 0 and state == "MEASURED_OK":
        return Verdict(
            REJECTED,
            "the post-sign-in identifier was absent (the 302 case: a sign-in page "
            "carrying a success code is not a pass)",
            corrected_query=f'probe_identifier_present{{service="{service}"}}',
        )

    if kind == "metric":
        query = str(evidence.get("query", "")).strip()
        if not query:
            return Verdict(REJECTED, "`evidence.query` is missing")
        result = (prom or query_metric)(query)
        if result is None:
            return Verdict(
                UNAVAILABLE, f"the metric store could not be reached to run {query!r}"
            )
        if not result:
            return Verdict(
                REJECTED,
                f"the query returns no series: {query!r}",
                corrected_query=f'probe_state{{service="{service}"}}',
            )
        return Verdict(ACCEPTED, envelope=env, warnings=warnings)

    # kind == "command"
    if "exit_code" not in evidence:
        return Verdict(REJECTED, "`evidence.exit_code` is missing for a command")
    try:
        code = int(evidence["exit_code"])
    except (TypeError, ValueError):
        return Verdict(REJECTED, "`evidence.exit_code` is not a number")
    if code != 0 and state == "MEASURED_OK":
        return Verdict(
            REJECTED,
            f"the command exited {code}; a failed command cannot support MEASURED_OK",
            corrected_query=str(evidence.get("command", "")),
        )
    out = evidence.get("output")
    if isinstance(out, str) and len(out.encode("utf-8")) > OUTPUT_LIMIT:
        env = {
            **env,
            "evidence": {
                **evidence,
                "output": out.encode("utf-8")[:OUTPUT_LIMIT].decode("utf-8", "ignore"),
            },
        }
        warnings.append(f"output truncated to {OUTPUT_LIMIT} bytes")
    return Verdict(ACCEPTED, envelope=env, warnings=warnings)


def envelopes_in(text):
    """Every ```claim block in a text, as (raw, parsed-or-None)."""
    out = []
    for raw in FENCE.findall(text or ""):
        try:
            out.append((raw, json.loads(raw)))
        except json.JSONDecodeError:
            out.append((raw, None))
    return out


def log_claim(entry, path=None):
    p = Path(path) if path else CLAIMS_LOG
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    except OSError:
        pass


def current_turn(session):
    """The turn counter the tool-call recorder keeps, so a claim can be tied to a turn."""
    d = os.environ.get("TOOL_CALL_RECORD_DIR") or str(ESTATE / "tool-calls")
    f = Path(d) / f"{session}.turn"
    try:
        return int(f.read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def gate_text(
    text, session="", surface="", now=None, prom=None, log=None, probes_dir=None
):
    """Gate a whole text. Returns (text, refusal): refusal None means write it; the text may
    have been rewritten (stale evidence becomes UNKNOWN, with the warning appended)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    blocks = envelopes_in(text)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {
        "ts": stamp,
        "session": session,
        "surface": surface,
        "turn": current_turn(session) if session else 0,
    }
    if MEASURED_WORD.search(text or "") and not blocks:
        entry = {
            **base,
            "service": "",
            "state": "",
            "kind": "none",
            "status": REJECTED,
            "reason": "measured state asserted with no claim block",
        }
        log_claim(entry, log)
        return text, Verdict(
            REJECTED,
            "the text asserts MEASURED_OK or MEASURED_FAIL and carries no "
            "```claim block; a measurement carries its evidence",
            corrected_query="python3 ~/.claude/scripts/claim_gate.py new --help",
        ).text()
    for raw, env in blocks:
        if env is None:
            log_claim(
                {
                    **base,
                    "service": "",
                    "state": "",
                    "kind": "none",
                    "status": REJECTED,
                    "reason": "claim block is not JSON",
                },
                log,
            )
            return text, Verdict(REJECTED, "a ```claim block is not valid JSON").text()
        v = validate(env, now=now, prom=prom, probes_dir=probes_dir)
        entry = {
            **base,
            "service": str(env.get("service", "")),
            "state": str((v.envelope or env).get("state", "")),
            "asserted_state": str(env.get("state", "")),
            "kind": str((env.get("evidence") or {}).get("kind", "none")),
            "lead": is_lead(env),
            "status": v.status,
            "reason": v.reason[:200],
            "warnings": v.warnings,
        }
        log_claim(entry, log)
        if not v.ok:
            return text, v.text()
        if v.warnings:
            new_raw = json.dumps(v.envelope, indent=1)
            text = text.replace(raw, new_raw + "\n", 1) if raw in text else text
            text = (
                text.rstrip("\n")
                + "\n"
                + "".join(f"\n(gate: {w})" for w in v.warnings)
                + "\n"
            )
    return text, None


def build_envelope(
    service, state, claim, command=None, query=None, prom=None, now=None
):
    """Make an envelope from a live command or a live query, running it now."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if command:
        r = subprocess.run(
            [
                shutil.which("sh") or "/bin/sh",
                "-c",
                command,
            ],  # the operator's own evidence command, pipes allowed
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (
            (r.stdout + r.stderr)
            .encode("utf-8")[:OUTPUT_LIMIT]
            .decode("utf-8", "ignore")
        )
        ev = {
            "kind": "command",
            "command": command,
            "exit_code": r.returncode,
            "output": out,
            "observed_at": stamp,
            "age_seconds": 0,
        }
    elif query:
        result = (prom or query_metric)(query)
        value = None
        if result:
            try:
                value = float(result[0]["value"][1])
            except (KeyError, IndexError, TypeError, ValueError):
                value = None
        ev = {
            "kind": "metric",
            "query": query,
            "value": value,
            "observed_at": stamp,
            "age_seconds": 0,
            "series": 0 if result is None else len(result),
        }
    else:
        ev = {"kind": "none"}
    return {"claim": claim, "state": state, "service": service, "evidence": ev}


def render(env):
    return "```claim\n" + json.dumps(env, indent=1) + "\n```"


# --- selftest ---------------------------------------------------------------------------------


def selftest():
    now = dt.datetime(2026, 8, 31, 6, 0, tzinfo=dt.timezone.utc)
    fresh = "2026-08-31T05:59:30Z"
    stale = "2026-08-31T05:00:00Z"
    cases = [
        (
            "measured with no evidence",
            {
                "claim": "a",
                "state": "MEASURED_OK",
                "service": "s",
                "evidence": {"kind": "none"},
            },
            REJECTED,
        ),
        (
            "stale evidence rewrites to UNKNOWN",
            {
                "claim": "a",
                "state": "MEASURED_OK",
                "service": "s",
                "evidence": {"kind": "command", "exit_code": 0, "observed_at": stale},
            },
            "UNKNOWN",
        ),
        (
            "metric with no series",
            {
                "claim": "a",
                "state": "MEASURED_OK",
                "service": "s",
                "evidence": {"kind": "metric", "query": "x", "observed_at": fresh},
            },
            REJECTED,
        ),
        (
            "failed command behind MEASURED_OK",
            {
                "claim": "a",
                "state": "MEASURED_OK",
                "service": "s",
                "evidence": {"kind": "command", "exit_code": 1, "observed_at": fresh},
            },
            REJECTED,
        ),
        (
            "banned token",
            {
                "claim": "backstage is up",
                "state": "MEASURED_OK",
                "service": "backstage",
                "evidence": {"kind": "command", "exit_code": 0, "observed_at": fresh},
            },
            REJECTED,
        ),
        (
            "the 302 case",
            {
                "claim": "a",
                "state": "MEASURED_OK",
                "service": "s",
                "evidence": {
                    "kind": "command",
                    "exit_code": 0,
                    "observed_at": fresh,
                    "probe_identifier_present": 0,
                },
            },
            REJECTED,
        ),
        (
            "UNKNOWN needs nothing",
            {"claim": "a", "state": "UNKNOWN", "service": "s"},
            ACCEPTED,
        ),
        (
            "a lead with a measured state",
            {
                "claim": "LEAD: reachable",
                "state": "MEASURED_OK",
                "service": "s",
                "source": "peer",
                "evidence": {"kind": "none"},
            },
            REJECTED,
        ),
        (
            "a lead with its source",
            {
                "claim": "LEAD: reachable",
                "state": "UNKNOWN",
                "service": "s",
                "source": "peer",
            },
            ACCEPTED,
        ),
        (
            "metric store unreachable",
            {
                "claim": "a",
                "state": "MEASURED_OK",
                "service": "s",
                "evidence": {"kind": "metric", "query": "x", "observed_at": fresh},
            },
            UNAVAILABLE,
        ),
        (
            "a fresh command pass",
            {
                "claim": "a",
                "state": "MEASURED_OK",
                "service": "s",
                "evidence": {"kind": "command", "exit_code": 0, "observed_at": fresh},
            },
            ACCEPTED,
        ),
    ]
    bad = 0
    for name, env, want in cases:
        prom = (
            (lambda q: None) if name == "metric store unreachable" else (lambda q: [])
        )
        v = validate(env, now=now, prom=prom, probes_dir="/nonexistent")
        got = v.envelope["state"] if (want == "UNKNOWN" and v.ok) else v.status
        flag = "ok  " if got == want else "FAIL"
        bad += got != want
        print(f"{flag}    claim-gate  {name}: {got}")
    text = "the store is MEASURED_OK now"
    _, refusal = gate_text(text, now=now, log=os.devnull)
    flag = "ok  " if refusal and refusal.startswith(REJECTED) else "FAIL"
    bad += not (refusal and refusal.startswith(REJECTED))
    print(f"{flag}    claim-gate  a measured word with no block is refused")
    return 1 if bad else 0


def main(argv):
    import argparse

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--selftest", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser(
        "check", help="gate a text or a bare envelope from FILE or stdin"
    )
    c.add_argument("path", nargs="?", default="-")
    c.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", ""))
    c.add_argument("--surface", default="cli")
    n = sub.add_parser(
        "new", help="run a command or query now and print the finished claim block"
    )
    n.add_argument("--service", required=True)
    n.add_argument("--state", required=True, choices=PERMITTED_STATES)
    n.add_argument("--claim", required=True)
    n.add_argument("--command")
    n.add_argument("--query")
    a = p.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "check":
        text = sys.stdin.read() if a.path == "-" else Path(a.path).read_text()
        stripped = text.strip()
        if stripped.startswith("{"):
            text = "```claim\n" + stripped + "\n```"
        out, refusal = gate_text(text, session=a.session, surface=a.surface)
        if refusal:
            print(refusal)
            return 2 if refusal.startswith(UNAVAILABLE) else 1
        print(out, end="")
        return 0
    if a.cmd == "new":
        env = build_envelope(
            a.service, a.state, a.claim, command=a.command, query=a.query
        )
        v = validate(env)
        print(render(v.envelope or env))
        if not v.ok:
            print(v.text(), file=sys.stderr)
            return 2 if v.status == UNAVAILABLE else 1
        for w in v.warnings:
            print("warning: " + w, file=sys.stderr)
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
