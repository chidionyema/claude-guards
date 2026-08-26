#!/usr/bin/env python3
"""pause-guard: LAW 48. A reply that parks a found defect behind founder permission is refused.

Founder, 2026-08-26 (crew#280): session 8f034e1e found the KINI worker down, ticketed it, and
wrote "I stop here since you asked for a status, not a repair; say 'fit it' and I start".
THE CLASS: a sentence that makes fixing a discovered defect conditional on the founder's say-so.
Stop hook (reads the last assistant message, same shape as vendor-lock-guard.py); --selftest
proves both ways. Exit 0 always; blocks by printing the decision JSON.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vendor_lock_guard_io import above_the_fold, last_assistant_text  # noqa: E402

PAUSE = re.compile(
    r"i\s+stop\s+here|stopp?ing\s+here\s+(?:since|because|as)\s+you\s+asked|awaiting\s+(?:your\s+)?"
    r"(?:permission|go[- ]ahead|approval)|should\s+i\s+fix\s+(?:this|it|that)\b|say\s+['\"]?fix\s+it['\"]?\s+and\s+i"
    r"|want\s+me\s+to\s+fix\s+(?:this|it|that)\b|shall\s+i\s+(?:fix|repair|proceed)",
    re.I,
)
FENCE = re.compile(r"```.*?```", re.S)


def offences(text: str) -> list[tuple[int, str]]:
    body = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), above_the_fold(text))
    return [(n, l.strip()) for n, l in enumerate(body.splitlines(), 1) if PAUSE.search(l)]


def selftest() -> int:
    real = ("INVENTORY: KINI is merged but not running.\nI stop here since you asked for a status, "
            "not a repair; say \"fix it\" and I start on crew#280 items 1-2.\n")
    fixed = ("INVENTORY: Found the KINI worker down (Temporal 7233 refused). Fixed it in idp#150; "
             "the worker is polling. Status is now green.\nSTAGED: retire the /tmp worktree. Reply 'hold' "
             "to cancel. Auto-activating in 60 minutes.\n")
    checks = [("refuses the real reply", len(offences(real)) == 1),
              ("refuses 'Should I fix this?'", len(offences("Should I fix this?")) == 1),
              ("allows the fixed reply", offences(fixed) == []),
              ("allows a plain question about scope", offences("Which repo should the spec live in?") == []),
              ("code blocks are not prose", offences("```\nI stop here\n```\n") == [])]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {n}")
    print(f"pause-guard selftest: {len(checks)-len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selftest"]:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("stop_hook_active"):
        return 0
    t = Path(payload.get("transcript_path", ""))
    if not t.is_file():
        return 0
    found = offences(last_assistant_text(t))
    if not found:
        return 0
    lines = ["PAUSED ON A FOUND DEFECT. LAW 48: continuous execution. Founder, 2026-08-26 (crew#280): "
             "'An autonomous organism does not ask for permission to heal a bleeding artery.'"]
    lines += [f"  line {n}: {l[:160]}" for n, l in found]
    lines.append("Fix it in this turn and report 'Found X broken. Fixed it in PR Y. Status is now green.' "
                 "Reversible work is announced STAGED: with a 60-minute timer, never asked (LAW 49).")
    print(json.dumps({"decision": "block", "reason": "\n".join(lines)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
