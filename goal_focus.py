"""Founder focus: one line rewrites every live session's goal (crew#395).

A library, not a guard: it is state management for ~/.claude/state/goal, imported by
goal-guard.py (--focus), board-deliver.py (a FOCUS: line on the board) and auto-objective.py
(the claim list under a focus). It left goal-guard.py on crew#398 because
policy/hand_rolled_policy.rego holds that guard at 960 lines: the hand-rolled guards are being
migrated to Rego, and a focus is not a rule that can be Rego, so it lives here on its own.
Every function takes `gg`, the loaded goal-guard module, for STATE_DIR, read_state,
write_state, state_path and ledger, so a test that repoints gg.STATE_DIR repoints this too.
"""
from __future__ import annotations

import json
import re
import sys
import time

FOCUS_SINCE_HOURS = 24
STOP = {"only", "focus", "this", "that", "with", "from", "then", "crew"}


def focus_path(gg):
    return gg.STATE_DIR / "FOCUS.json"


def read_focus(gg) -> dict:
    """The standing focus, or {} when none is set. Empty text means no focus."""
    try:
        d = json.loads(focus_path(gg).read_text())
        return d if d.get("text") else {}
    except Exception:
        return {}


def focus(gg, text: str, source: str = "", since_hours: float = FOCUS_SINCE_HOURS) -> list[str]:
    """Rewrite the goal of every session whose state file moved in the last since_hours.
    Returns the session ids rewritten. The old goal is kept as prev_goal so a session can
    see what it was pulled off. Incident, 2026-08-26: the founder said "you have one
    mission" and a session stayed on crew#66 because its state file still said so."""
    text = " ".join(text.split())
    if not text:
        return []
    cut = time.time() - since_hours * 3600
    done: list[str] = []
    gg.STATE_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(gg.STATE_DIR.glob("*.json")):
        if f.name == "FOCUS.json" or f.stat().st_mtime < cut:
            continue
        sess = f.stem
        st = gg.read_state(sess)
        if st.get("goal") != text:
            st["prev_goal"] = st.get("goal", "")
        st["goal"] = text
        st["focus_source"] = source
        st["focus_at"] = int(time.time())
        gg.write_state(sess, st)
        done.append(sess)
    rec = {"text": text, "source": source, "at": int(time.time()), "sessions": done}
    tmp = focus_path(gg).with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(focus_path(gg))
    gg.ledger({"t": int(time.time()), "kind": "focus", "source": source[:120],
               "goal": text[:200], "sessions": [d[:8] for d in done]})
    return done


def focus_filter(items: list, focus_text: str) -> list:
    """The board items a session may be told to claim while a focus stands: the item the
    focus names by number, or one whose title shares a word of four letters or more with
    it. No focus, no filtering. Under a KINI focus crew#66 (fly) is never offered."""
    if not focus_text:
        return items
    nums = {int(n) for n in re.findall(r"crew#(\d+)", focus_text)}
    words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", focus_text)} - STOP
    return [i for i in items
            if i.get("number") in nums or any(w in (i.get("title") or "").lower() for w in words)]


def cli(gg, argv: list[str]) -> int:
    """`goal-guard.py --focus '<line>' [--source s] [--since-hours h]`."""
    i = argv.index("--focus")
    text = argv[i + 1] if len(argv) > i + 1 else ""
    src = argv[argv.index("--source") + 1] if "--source" in argv else "cli"
    hrs = float(argv[argv.index("--since-hours") + 1]) if "--since-hours" in argv else FOCUS_SINCE_HOURS
    if not text.strip():
        print("--focus needs the founder's line, e.g. --focus 'crew#284: finish KINI'", file=sys.stderr)
        return 1
    done = focus(gg, text, src, hrs)
    print(f"focus set for {len(done)} live session(s) (moved in the last {hrs:g}h): {text}")
    for d in done:
        print(f"  {d[:12]}")
    return 0


def selftest(gg, ck) -> None:
    """Called from goal-guard.py --selftest inside its temporary STATE_DIR."""
    import os
    print("focus -- one founder line rewrites every live session (crew#395)")
    gg.write_state("live1", {"goal": "crew#66: eradicate fly", "run": 0, "last_progress": "", "last_progress_at": 0, "fired": 0, "calls": 0})
    gg.write_state("stale1", {"goal": "crew#13: retire hermes", "run": 0, "last_progress": "", "last_progress_at": 0, "fired": 0, "calls": 0})
    os.utime(gg.state_path("stale1"), (time.time() - 3 * 86400, time.time() - 3 * 86400))
    done = focus(gg, "crew#284: finish KINI, nothing else", "selftest")
    ck("the live session is rewritten", gg.read_state("live1")["goal"] == "crew#284: finish KINI, nothing else")
    ck("the old goal is kept as prev_goal", gg.read_state("live1")["prev_goal"] == "crew#66: eradicate fly")
    ck("the stale session is left alone", gg.read_state("stale1")["goal"] == "crew#13: retire hermes")
    ck("the live session is reported and the stale one is not", "live1" in done and "stale1" not in done)
    ck("the focus is on disk", read_focus(gg)["text"].startswith("crew#284"))
    ck("an empty focus rewrites nothing", focus(gg, "   ", "selftest") == [])
    items = [{"number": 66, "title": "eradicate fly io"}, {"number": 284, "title": "KINI delivered"},
             {"number": 306, "title": "hard execution chain for kini"}]
    kept = [i["number"] for i in focus_filter(items, read_focus(gg)["text"])]
    ck("under a KINI focus crew#66 is never offered", 66 not in kept)
    ck("the named item and a title match are offered", kept == [284, 306])
    ck("no focus, no filtering", focus_filter(items, "") == items)
