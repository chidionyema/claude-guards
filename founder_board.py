#!/usr/bin/env python3
"""The founder's board: what is done, what is broken, what is waiting on him.

Founder directive 2026-08-21: "we dothave a borard", "should notave to be asking these
questions", "need to know what is done, what is outstanding before going tinto liower level
detail", "so updates neeed to be top notch".

WHAT THIS IS FOR. He was opening the same page an hour apart and seeing nothing change, and
having to ask each time. A board he can open answers the question without a person in the loop,
which is the "frictioless and barelt any hunan inloop" requirement applied to reporting itself.

WHY IT IS GENERATED AND NEVER WRITTEN BY HAND. This estate's most expensive repeated failure is
prose that was true once. A hand-written status page drifts from the machine within hours and
then costs more than no page, because it is believed. Every row here comes from a command, and
every row carries the command that produced it so any line can be re-run and checked.

THREE RULES THE COLLECTORS OBEY, each one a failure this estate has already paid for:

  1. A collector that fails reports UNKNOWN with the reason. It NEVER reports zero.
     A dead probe and a clean probe both print no findings; only one of them is good news.
     (memory: an-audit-that-crashes-reports-nothing)
  2. A non-zero exit is not automatically an error. process_audit.py exits 1 BECAUSE it found
     failures -- that is it working. Each collector says for itself which exits are fine.
  3. Every row carries the age of its measurement. A number with no age is a claim about the
     past presented as a claim about now.

    python3 ~/.claude/scripts/founder_board.py              # print it
    python3 ~/.claude/scripts/founder_board.py --html OUT   # write the page
    python3 ~/.claude/scripts/founder_board.py --json       # machine-readable
    python3 ~/.claude/scripts/founder_board.py --selftest
"""
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".claude", "state", "founder_board.json")
PROSPECTOR = os.path.join(HOME, "Documents", "code", "prospector")

GOOD, BAD, WARN, UNKNOWN = "good", "bad", "warn", "unknown"


def sh(cmd: list[str], timeout: int, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a command. Returns (rc, stdout, stderr). rc 124 is this function's timeout."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except (OSError, ValueError) as e:
        return 127, "", f"{type(e).__name__}: {e}"


class Row:
    __slots__ = ("state", "label", "value", "detail", "command", "measured_at")

    def __init__(self, state, label, value, detail="", command=""):
        self.state, self.label, self.value = state, label, value
        self.detail, self.command = detail, command
        self.measured_at = time.time()

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


def _unknown(label, why, command=""):
    """The only honest answer when a probe could not run. Never a zero."""
    return Row(UNKNOWN, label, "UNKNOWN", why, command)


# --------------------------------------------------------------------------- collectors

def collect_spend() -> list[Row]:
    """Money. This is the platform view and it goes first for that reason."""
    cmd = ["/usr/local/bin/python3", os.path.join(HOME, ".claude", "scripts",
                                                  "estate_cost_sentinel.py"), "--digest",
           "--dry-run"]
    rc, out, err = sh(cmd, 90)
    # rc 1 means "over the warn line", which is a finding, not a failure of the probe.
    if rc not in (0, 1) or not out.strip():
        return [_unknown("Claude spend today", err.strip() or f"exit {rc}", " ".join(cmd))]
    spend = cap = None
    for line in out.splitlines():
        if "of $" in line and "cap" in line:
            try:
                left, right = line.split(" of $", 1)
                spend = float(left.rsplit("$", 1)[1].replace(",", ""))
                cap = float(right.split()[0].replace(",", ""))
            except (IndexError, ValueError):
                pass
            break
    if spend is None or cap is None:
        return [_unknown("Claude spend today", "digest printed no spend line", " ".join(cmd))]
    armed = "DISARMED" not in out
    rows = [Row(BAD if spend > cap else GOOD, "Claude spend today",
                f"${spend:,.2f} of a ${cap:,.0f} cap",
                f"{spend / cap:.1f}x the cap" if spend > cap else "inside the cap",
                " ".join(cmd))]
    rows.append(Row(GOOD if armed else BAD, "Automatic spend halt",
                    "ARMED" if armed else "DISARMED",
                    "" if armed else "nothing stops the spend; set halt_usd in "
                                     "~/.claude/estate-budget.json",
                    "grep halt_usd ~/.claude/estate-budget.json"))
    return rows


def collect_estate_checks() -> list[Row]:
    """The estate's own auditor. Its exit 1 means it found problems -- that is it working."""
    cmd = [os.path.join(PROSPECTOR, ".venv", "bin", "python"),
           os.path.join(PROSPECTOR, "scripts", "process_audit.py"), "--json"]
    rc, out, err = sh(cmd, 600, cwd=PROSPECTOR)
    if rc not in (0, 1):
        return [_unknown("Estate checks", err.strip()[:200] or f"exit {rc}", " ".join(cmd))]
    try:
        payload = json.loads(out)
    except ValueError as e:
        return [_unknown("Estate checks", f"audit printed no JSON ({e})", " ".join(cmd))]
    failing = [(s["title"], r) for s in payload.get("sections", [])
               for r in s.get("rows", []) if r.get("grade") == "bad"]
    rows = [Row(GOOD if not failing else BAD, "Estate checks failing",
                str(len(failing)),
                f"{payload.get('warnings', 0)} warnings as well", " ".join(cmd))]
    for title, r in failing:
        rows.append(Row(BAD, f"{title} — {r['name']}", "FAIL", r.get("detail", "")[:220],
                        " ".join(cmd)))
    return rows


def collect_prs() -> list[Row]:
    """What is in flight. A PR nobody can merge is the pipeline stopped (LAW 12)."""
    cmd = ["gh", "pr", "list", "--repo", "chidionyema/prospector", "--limit", "30",
           "--json", "number,title,mergeable,statusCheckRollup,createdAt,isDraft"]
    rc, out, err = sh(cmd, 90)
    if rc != 0:
        return [_unknown("Open pull requests", err.strip()[:200] or f"exit {rc}", " ".join(cmd))]
    try:
        prs = json.loads(out)
    except ValueError as e:
        return [_unknown("Open pull requests", str(e), " ".join(cmd))]
    rows = [Row(GOOD if len(prs) <= 5 else WARN, "Open pull requests", str(len(prs)),
                "", " ".join(cmd))]
    now = time.time()
    for pr in prs:
        checks = pr.get("statusCheckRollup") or []
        red = sorted({c.get("name", "?") for c in checks
                      if c.get("conclusion") not in ("SUCCESS", "NEUTRAL", "SKIPPED", None)})
        pending = [c for c in checks if c.get("conclusion") is None]
        try:
            age_h = (now - time.mktime(time.strptime(pr["createdAt"], "%Y-%m-%dT%H:%M:%SZ"))
                     + time.timezone) / 3600
        except (KeyError, ValueError):
            age_h = float("nan")
        conflicting = pr.get("mergeable") == "CONFLICTING"
        state = BAD if (red or conflicting) else (WARN if pending else GOOD)
        what = ("needs a rebase" if conflicting else
                f"red: {', '.join(red)}" if red else
                f"{len(pending)} check(s) still running" if pending else "green, mergeable")
        rows.append(Row(state, f"PR #{pr['number']} — {pr['title'][:58]}", what,
                        f"open {age_h:.0f}h", f"gh pr view {pr['number']}"))
    return rows


def collect_requirements() -> list[Row]:
    """What the founder asked for, and how much of it is proven done."""
    cmd = ["git", "-C", PROSPECTOR, "show", "origin/main:docs/REQUIREMENTS.md"]
    rc, out, err = sh(cmd, 60)
    if rc != 0:
        return [_unknown("Requirements register", err.strip()[:160] or f"exit {rc}",
                         " ".join(cmd))]
    tally, total = {}, 0
    for line in out.splitlines():
        if not line.startswith("| R"):
            continue
        total += 1
        cells = [c.strip() for c in line.split("|")]
        state = "UNSTATED"
        for c in cells:
            bare = c.replace("*", "").strip()
            if bare in ("DONE", "PARTLY", "NOT STARTED", "IN PROGRESS", "unproven"):
                state = bare
                break
            if bare.startswith("DONE"):          # "DONE (engine + config page)"
                state = "DONE"
                break
        tally[state] = tally.get(state, 0) + 1
    if not total:
        return [_unknown("Requirements register", "no R-rows found on origin/main",
                         " ".join(cmd))]
    done = tally.get("DONE", 0)
    rows = [Row(GOOD if done == total else WARN, "Requirements proven done",
                f"{done} of {total}",
                ", ".join(f"{v} {k.lower()}" for k, v in sorted(tally.items())),
                " ".join(cmd))]
    return rows


def collect_launchd() -> list[Row]:
    """Every job that is supposed to keep this estate running by itself."""
    rc, out, err = sh(["launchctl", "list"], 30)
    if rc != 0:
        return [_unknown("Background jobs", err.strip()[:160] or f"exit {rc}", "launchctl list")]
    watched, dead = 0, []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid, status, label = parts
        if not (label.startswith("com.prospector") or label.startswith("com.estate")
                or label.startswith("ai.hermes") or label.startswith("com.chidionyema")):
            continue
        watched += 1
        try:
            code = int(status)
        except ValueError:
            continue
        # A negative status is a signal, which for a periodic job usually means it is running
        # right now. Only a positive exit code is a job that ran and failed.
        if code > 0:
            dead.append(f"{label} (exit {code})")
    rows = [Row(GOOD if not dead else BAD, "Background jobs failing",
                f"{len(dead)} of {watched}", "; ".join(dead[:6]), "launchctl list")]
    return rows


def collect_founder_decisions() -> list[Row]:
    """Questions only he can answer. They are not blocked on work, they block work."""
    cmd = ["git", "-C", PROSPECTOR, "show", "origin/main:docs/REQUIREMENTS.md"]
    rc, out, _ = sh(cmd, 60)
    if rc != 0:
        return [_unknown("Waiting on the founder", f"exit {rc}", " ".join(cmd))]
    qs = [l for l in out.splitlines() if l.startswith("| Q") and "---" not in l]
    return [Row(WARN if qs else GOOD, "Waiting on a founder ruling", str(len(qs)),
                "; ".join(l.split("|")[2].strip()[:70] for l in qs[:4]), " ".join(cmd))]


COLLECTORS = [
    ("Money", collect_spend),
    ("Work in flight", collect_prs),
    ("What is broken", collect_estate_checks),
    ("The machine that runs itself", collect_launchd),
    ("What was asked for", collect_requirements),
    ("Waiting on you", collect_founder_decisions),
]


def build() -> dict:
    sections = []
    for title, fn in COLLECTORS:
        started = time.time()
        try:
            rows = fn()
        except Exception as e:                    # noqa: BLE001 -- rule 1: never report zero
            rows = [_unknown(title, f"collector raised {type(e).__name__}: {e}")]
        sections.append({"title": title, "took_s": round(time.time() - started, 1),
                         "rows": [r.as_dict() for r in rows]})
    flat = [r for s in sections for r in s["rows"]]
    return {
        "generated_at": time.time(),
        "sections": sections,
        "bad": sum(1 for r in flat if r["state"] == BAD),
        "unknown": sum(1 for r in flat if r["state"] == UNKNOWN),
    }


# --------------------------------------------------------------------------- rendering

def render_text(board: dict) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(board["generated_at"]))
    mark = {GOOD: "  ok  ", BAD: " FAIL ", WARN: " warn ", UNKNOWN: "  ??  "}
    out = [f"FOUNDER BOARD — {stamp}",
           f"{board['bad']} failing, {board['unknown']} could not be measured", ""]
    for s in board["sections"]:
        out.append(f"=== {s['title']} ({s['took_s']}s) ===")
        for r in s["rows"]:
            out.append(f"[{mark[r['state']]}] {r['label'][:56]:<56} {r['value']}")
            if r["detail"]:
                out.append(f"           {r['detail'][:100]}")
        out.append("")
    return "\n".join(out)


def render_html(board: dict) -> str:
    e = html.escape
    stamp = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(board["generated_at"]))
    headline = ("Everything measured is green." if not board["bad"]
                else f"{board['bad']} thing{'s' if board['bad'] != 1 else ''} broken.")
    n = board["unknown"]
    # An unmeasured row is not a green row. It is said out loud, at the top, in words.
    unmeasured = "" if not n else f" {n} thing{'s' if n != 1 else ''} could not be measured."
    parts = ["<title>Founder Board</title>", _CSS,
             f'<header><p class="eyebrow">Estate status</p><h1>{e(headline)}</h1>'
             f'<p class="stamp">Measured {e(stamp)}. Every row below is a command, not a claim.'
             f'<header><p class="eyebrow">Estate status</p><h1>{e(headline)}</h1>'
             f'<p class="stamp">Measured {e(stamp)}. Every row below is a command, not a claim.'
             f'{unmeasured}</p></header>',
             "<main>"]
    for s in board["sections"]:
        parts.append(f'<section><h2>{e(s["title"])}</h2><ul class="rows">')
        for r in s["rows"]:
            parts.append(
                f'<li class="row {r["state"]}"><span class="label">{e(r["label"])}</span>'
                f'<span class="value">{e(str(r["value"]))}</span>'
                + (f'<span class="detail">{e(r["detail"])}</span>' if r["detail"] else "")
                + (f'<code>{e(r["command"])}</code>' if r["command"] else "")
                + "</li>")
        parts.append("</ul></section>")
    parts.append("</main>")
    return "\n".join(parts)


_CSS = """<style>
:root{--bg:#fbfaf8;--ink:#1b1a18;--dim:#6c6862;--line:#e3ded6;--card:#ffffff;
--good:#2f7d51;--bad:#b3261e;--warn:#9a6b00;--unk:#5b5f6b;--accent:#1b4d7a;}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--bg:#15161a;--ink:#eceae6;--dim:#9a968f;--line:#2c2e35;--card:#1c1e23;
--good:#6ec48d;--bad:#ff8a80;--warn:#e0b352;--unk:#9aa0ae;--accent:#7fb3e0;}}
:root[data-theme="dark"]{--bg:#15161a;--ink:#eceae6;--dim:#9a968f;--line:#2c2e35;--card:#1c1e23;
--good:#6ec48d;--bad:#ff8a80;--warn:#e0b352;--unk:#9aa0ae;--accent:#7fb3e0;}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;padding:2rem 1.25rem 4rem;
font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;}
header,main{max-width:62rem;margin:0 auto}
.eyebrow{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin:0}
h1{font-size:clamp(1.6rem,5vw,2.4rem);margin:.3rem 0 .5rem;text-wrap:balance;letter-spacing:-.02em}
.stamp{color:var(--dim);font-size:.9rem;margin:0 0 2rem}
h2{font-size:.8rem;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);
margin:2rem 0 .6rem;font-weight:600}
.rows{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.4rem}
.row{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--unk);
border-radius:6px;padding:.7rem .9rem;display:grid;grid-template-columns:1fr auto;gap:.2rem .9rem}
.row.good{border-left-color:var(--good)}.row.bad{border-left-color:var(--bad)}
.row.warn{border-left-color:var(--warn)}.row.unknown{border-left-color:var(--unk)}
.label{font-weight:550}
.value{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.row.bad .value{color:var(--bad)}.row.good .value{color:var(--good)}
.row.warn .value{color:var(--warn)}.row.unknown .value{color:var(--unk)}
.detail{grid-column:1/-1;color:var(--dim);font-size:.87rem}
code{grid-column:1/-1;color:var(--dim);font-size:.76rem;font-family:ui-monospace,Menlo,monospace;
overflow-x:auto;white-space:pre;display:block;opacity:.75}
@media(max-width:34rem){.row{grid-template-columns:1fr}.value{text-align:left}}
</style>"""


# --------------------------------------------------------------------------- selftest

def selftest() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        if not cond:
            print(f"FAIL: {name}")
            ok = False

    # RULE 1: a collector that raises must produce UNKNOWN, never an empty green section.
    def boom():
        raise RuntimeError("probe is dead")
    saved = COLLECTORS[:]
    COLLECTORS[:] = [("Broken probe", boom)]
    b = build()
    COLLECTORS[:] = saved
    rows = b["sections"][0]["rows"]
    check("a raising collector yields exactly one row", len(rows) == 1)
    check("a raising collector reports UNKNOWN", rows[0]["state"] == UNKNOWN)
    check("a raising collector is not counted as good", b["unknown"] == 1 and b["bad"] == 0)
    check("the reason survives", "probe is dead" in rows[0]["detail"])

    # RULE 3: every row carries when it was measured.
    check("rows are timestamped", all(r["measured_at"] > 0
                                      for s in b["sections"] for r in s["rows"]))

    # A timeout is reported as a timeout, not as a zero.
    rc, _, err = sh(["/bin/sleep", "5"], 1)
    check("sh reports a timeout as 124", rc == 124 and "timed out" in err)
    rc, _, err = sh(["/definitely/not/a/binary"], 5)
    check("sh reports an unspawnable command", rc == 127 and err)

    # The renderers must survive every state, including UNKNOWN with no command.
    fake = {"generated_at": time.time(), "bad": 1, "unknown": 1, "sections": [
        {"title": "T", "took_s": 0.0, "rows": [
            Row(GOOD, "g", "1").as_dict(), Row(BAD, "b<&>", "2", "d", "c").as_dict(),
            Row(WARN, "w", "3").as_dict(), _unknown("u", "why").as_dict()]}]}
    txt, page = render_text(fake), render_html(fake)
    check("text render mentions every row", all(k in txt for k in ("g", "w", "u")))
    check("html escapes the label", "b&lt;&amp;&gt;" in page)
    check("html defines colours on bare :root", ":root{--bg:" in page)
    check("html paints the body background", "body{background:var(--bg)" in page)

    print("PASS: a dead collector reports UNKNOWN, never zero." if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", metavar="PATH")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    board = build()
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as fh:
            json.dump(board, fh, indent=2)
    except OSError as e:
        print(f"[board] could not save state: {e}", file=sys.stderr)

    if args.html:
        with open(args.html, "w") as fh:
            fh.write(render_html(board))
        print(f"wrote {args.html}")
    if args.json:
        print(json.dumps(board, indent=2))
    elif not args.html:
        print(render_text(board))
    return 1 if board["bad"] else 0


if __name__ == "__main__":
    sys.exit(main())
