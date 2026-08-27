#!/usr/bin/env python3
"""Refuse a reply that tells the founder to run, type, paste, open or click something.

LAW 31: the founder does not run scripts. LAW 20: seamless is the deliverable. The rule sat in
~/AGENTS.md as prose while crew#423's enforcement map graded it "absent": no guard, so every
session could still end a reply with "run `make deploy` and paste the output". A rule that only
lives in a file you can read and still break is the floor; this is the machine that refuses it.

WHAT IT READS. The last assistant message in the Stop transcript, above the first `---` line,
the same fold jargon-guard uses. Below the fold is evidence and is not checked.

WHAT IT REFUSES. A line whose first words are an imperative aimed at a person: run, type,
execute, paste, open, click, go to, install, copy, and "you need to / you'll need to / please
run". One such line is enough.

WHAT IT PERMITS, and why the guard is not an outage (LAW 38):
  - `Use:` lines. The INVENTORY handoff format carries exactly one command the founder may
    choose to use; that line is the format, not a chore handed back.
  - `FOUNDER ACTION:` lines, which blocker-guard already gates to physical and billing steps.
  - `STAGED:` lines, whose only ask is the word "hold".
  - Anything inside a code fence or backticks that is not the start of a sentence.
  - Replies with no text above the fold.

WHY IT CANNOT LOOP. Copied from jargon-guard: at most three blocks per session, never twice
for the same text.

  python3 founder-imperative-guard.py --selftest   # proves it blocks the ask and passes the rewrite
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = Path.home() / ".claude" / "state" / "founder-imperative-guard.json"
MAX_BLOCKS_PER_SESSION = 3

ALLOWED_PREFIX = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:Use|FOUNDER ACTION|STAGED|Expect|Evidence):", re.I)
IMPERATIVE = re.compile(
    r"^\s*(?:[-*]\s*|\d+[.)]\s*)?(?:\*\*)?"
    r"(?:(?:please|then|now|just)\s+)?"
    r"(?:you(?:'ll| will)? need to\s+|you (?:have|need) to\s+)?"
    r"(?:run|type|execute|paste|open|click|go to|navigate to|install|copy|tap|ssh into|log in to|login to)\b",
    re.I,
)


def _jargon():
    spec = importlib.util.spec_from_file_location("jargon_guard", HERE / "jargon-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def offences(text: str) -> list[str]:
    """Lines above the fold that hand the founder a chore."""
    jg = _jargon()
    found = []
    for line in jg.above_the_fold(text).splitlines():
        if ALLOWED_PREFIX.match(line):
            continue
        if IMPERATIVE.match(line):
            found.append(line.strip())
    return found


def report(found: list[str]) -> str:
    lines = ["THE FOUNDER DOES NOT RUN SCRIPTS (LAW 31). This reply hands him a chore:"]
    lines += ["  > " + f[:120] for f in found]
    lines.append("")
    lines.append("Do it yourself, or make it a scheduled job, a workflow_dispatch, or a STAGED: line. "
                 "A command he may choose to use goes on the INVENTORY `Use:` line, and a physical or "
                 "billing step is a FOUNDER ACTION: line. Rewrite the text above the --- line and stop again.")
    return "\n".join(lines)


def selftest() -> int:
    bad = ("INVENTORY: the deploy is staged.\n"
           "Run `make deploy` and paste the output here.\n"
           "Then open a browser at the console and click Approve.\n"
           "---\nevidence: run `pytest` (below the fold, not checked)")
    good = ("INVENTORY: the deploy runs on a schedule now.\n"
            "Built: a workflow_dispatch deploy.\n"
            "Use: `gh workflow run deploy.yml`\n"
            "Expect: the run is green in 4 minutes.\n"
            "STAGED: rotating the key. Reply 'hold' to cancel. Auto-activating in 60 minutes.\n"
            "FOUNDER ACTION: tap the YubiKey when the phone buzzes.\n"
            "The job runs itself; nothing to run by hand.\n"
            "---\nrun `pytest -q` shows 3 passed")
    b, g = offences(bad), offences(good)
    assert len(b) == 2, b
    assert g == [], g
    print("selftest OK: blocks %d chore line(s) in the ask, passes the rewrite" % len(b))
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}
    path = payload.get("transcript_path") or ""
    if not path or not os.path.exists(path):
        return 0
    jg = _jargon()
    try:
        text = jg.last_assistant_text(Path(path))
    except OSError:
        return 0
    if not text:
        return 0
    found = offences(text)
    if not found:
        return 0
    session = str(payload.get("session_id") or "unknown")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        state = {}
    mine = state.get(session) or {"count": 0, "seen": []}
    if digest in mine["seen"] or mine["count"] >= MAX_BLOCKS_PER_SESSION:
        return 0
    mine["count"] += 1
    mine["seen"] = (mine["seen"] + [digest])[-20:]
    state[session] = mine
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print(report(found), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
