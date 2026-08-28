#!/usr/bin/env python3
"""Stop hook (crew#306 CP1 + CP4). A session with no ACTIVE goal does not end: it is handed
the oldest open unclaimed crew item, the claim is posted, and the stop is refused until the
agent has executed against it or declared a validated BLOCKED:.

Founder, 2026-08-26: "The session cannot end. The agent must execute or declare BLOCKED:.
Only escape: founder says STOP."

Words the founder can say (last user message, exact):
  STOP       goal cleared, claim released, session may end
  RELEASE    same, and the item is reassigned by the next session that stops goalless
  BLOCKED:   he authorises the blocker himself

A BLOCKED: reply from the agent must carry Tried: Error: Need: Who:. With all four it is
posted on the claimed issue and the stop is permitted; without them it is refused and a
`false_blocker` row goes on the ledger.

Fails open only on BLIND: the board unreadable, the transcript unreadable. A kill switch
exists for an outage: touch ~/.claude/state/auto-objective.off.

Selftest: python3 auto-objective.py --selftest.  Scan (CP4): python3 auto-objective.py --scan.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import estate_board as board  # noqa: E402

OFF = Path(os.path.expanduser("~/.claude/state/auto-objective.off"))
BLOCKED_STALE_S = 3600
RED_LABEL = "red-alert"


def _gg():
    spec = importlib.util.spec_from_file_location("goal_guard", HERE / "goal-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _in_flight(transcript: str) -> list[str]:
    try:
        spec = importlib.util.spec_from_file_location("idle_guard", HERE / "idle-guard.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        return mod.in_flight(transcript)
    except Exception:
        return []


def retry_decision(payload: dict, pending: list[str]) -> dict | None:
    """CP2, idle-guard v2. THE TRIGGER IS OPEN WORK, NOT RUN COUNT.

    Founder word, 2026-08-28: "ok do it", on the finding that this escalation fired 8 times in
    one session and 6 of those were wrong. Every wrong one had the same shape: runs in flight,
    a next step that depended on them, and a board-claim prompt that forced a context switch
    mid-task. A background run IS open work; grading it as "nothing independent to do" was the
    guard reading the least idle state as the most idle one, and it cost more wall clock than
    the idleness it was written for. The harness re-invokes the session when a run reports, so
    runs in flight now permit the retry outright — no WAITING: wording to get right, no ledger
    row for a session that was working.

    KEPT: the case the guard was actually written for — a retry with NO open work at all while
    the board carries unclaimed items. That claim is still false, still refused, and still goes
    on the ledger as `false_idle`. Escapes unchanged: a validated BLOCKED:, or founder
    STOP / RELEASE.
    Lives here, not in idle-guard.py: hand-rolled guards are frozen at their line count."""
    user, reply = board.last_texts(payload.get("transcript_path") or "")
    if board.founder_word(user):
        return None
    if reply.lstrip().startswith(board.BLOCKED) and not board.blocked_missing(reply):
        return None
    if pending:
        # crew#506 CP2, widened by the founder word of 2026-08-28: a run in flight is a reason to
        # end the turn, not a claim of idleness, and it is one whether or not the reply says so.
        # No ledger row: a session with work in flight is not an event.
        return None
    issues = board.open_issues()
    if issues is None:
        board.ledger({"guard": "idle-guard-v2", "event": "blind", "session": (payload.get("session_id") or "")[:8]})
        return None
    items = board.unclaimed(issues)
    gg = _gg()
    items = __import__('goal_focus').focus_filter(items, __import__('goal_focus').read_focus(gg).get("text", ""))  # crew#395: a focus narrows the claim list
    if not items:
        return None
    board.ledger({"guard": "idle-guard-v2", "event": "false_idle", "session": (payload.get("session_id") or "")[:8],
                  "runs": pending, "unclaimed": [i["number"] for i in items[:5]]})
    names = ", ".join(f"crew#{i['number']} {i['title'][:40]}" for i in items[:3])
    return {"decision": "block",
            "reason": f"[idle-guard v2] {len(pending)} run(s) still in flight and you asked to stop "
                      f"again. The board has {len(items)} unclaimed open item(s): {names}. "
                      "\"Nothing independent to do\" is false while that list is not empty, and it is "
                      "on the ledger. Claim one and start it now, or declare BLOCKED: with Tried: "
                      "Error: Need: Who:."}


def decide(payload: dict, gg=None) -> dict | None:
    """None permits; a dict is the block decision."""
    if OFF.exists():
        return None
    gg = gg or _gg()
    if payload.get("stop_hook_active"):
        # Not gated on `pending` any more: run count was the old trigger and it was the wrong
        # one. retry_decision() permits outright when runs are in flight, and grades the retry
        # only when the session has no open work.
        r = retry_decision(payload, _in_flight(payload.get("transcript_path") or ""))
        if r:
            return r
    session = payload.get("session_id") or ""
    transcript = payload.get("transcript_path") or ""
    if not session or not transcript or not os.path.exists(transcript):
        return None
    st = gg.read_state(session)
    lane = os.environ.get("CLAUDE_LANE", "default")
    user, reply = board.last_texts(transcript)
    goal = st.get("goal", "")
    num = board.goal_number(goal)

    if user.strip().startswith("FOCUS:"):
        # crew#395: a founder FOCUS: line rewrites every live session's goal, this one
        # included, before any session reads a transcript and asks. Nothing waits on him.
        text = user.strip()[len("FOCUS:"):].strip()
        done = __import__('goal_focus').focus(gg, text, f"terminal:{session[:8]}") if text else []
        board.ledger({"guard": "auto-objective", "event": "focus", "session": session[:8],
                      "sessions": len(done), "goal": text[:200]})
        return None
    word = board.founder_word(user)
    if word in ("STOP", "RELEASE"):
        if num and st.get("auto_claimed") == num:
            board.release(num, session, f"founder said {word}")
        st["goal"] = ""; st["auto_claimed"] = 0
        gg.write_state(session, st)
        board.ledger({"guard": "auto-objective", "event": word.lower(), "session": session[:8], "item": num})
        return None
    if word == "BLOCKED":
        board.ledger({"guard": "auto-objective", "event": "founder_blocked", "session": session[:8], "item": num})
        return None

    if reply.lstrip().startswith(board.BLOCKED):
        missing = board.blocked_missing(reply)
        if missing:
            board.ledger({"guard": "auto-objective", "event": "false_blocker", "session": session[:8],
                          "item": num, "missing": missing})
            return {"decision": "block",
                    "reason": f"[auto-objective] BLOCKED: is not validated. Missing {', '.join(missing)}. "
                              "Give what you tried, the exact error, what you need and who can "
                              "unblock, one line each, then stop again. A false blocker is a rogue "
                              "session and is on the ledger."}
        if num:
            board.comment(num, reply.strip()[:4000])
        st["blocked_at"] = int(time.time())
        gg.write_state(session, st)
        board.ledger({"guard": "auto-objective", "event": "blocked", "session": session[:8], "item": num})
        return None

    if goal:
        if st.get("auto_claimed") and not st.get("last_progress_at", 0) > st.get("auto_claimed_at", 0):
            return {"decision": "block",
                    "reason": f"[auto-objective] OBJECTIVE {goal} was assigned and nothing has been "
                              "executed against it. Execute now, or declare BLOCKED: with Tried: "
                              "Error: Need: Who:. Founder word STOP is the only other exit."}
        return None

    # crew#527 CP3: the board assigns. An item this session already holds (the board's CLAIM, or
    # its own) is its objective; only a session holding nothing takes the top of the rank.
    item = board.assignment_for(session) or board.next_unclaimed()
    if item == "BLIND":
        board.ledger({"guard": "auto-objective", "event": "blind", "session": session[:8]})
        return None
    if item is None:
        board.ledger({"guard": "auto-objective", "event": "board_empty", "session": session[:8]})
        return None
    num = item["number"]
    goal = f"crew#{num}: {item['title']}"
    st["goal"] = goal; st["auto_claimed"] = num; st["auto_claimed_at"] = int(time.time())
    gg.write_state(session, st)
    if board.claimed_by(item) is None:
        board.claim(num, session, lane, "auto-objective: session stopped with no ACTIVE goal")
    board.ledger({"guard": "auto-objective", "event": "assigned", "session": session[:8], "item": num})
    return {"decision": "block",
            "reason": f"[auto-objective] No ACTIVE goal, so one is assigned: {goal} "
                      f"(https://github.com/{board.REPO}/issues/{num}). The claim comment is posted. "
                      "Read the issue, define done in commands, execute. This session does not end "
                      "until progress is on disk or you declare BLOCKED: with Tried: Error: Need: Who:."}


def scan() -> int:
    """CP4: every BLOCKED: comment older than 1h with no VALID:/INVALID: reply reaches the
    founder; every INVALID: reply flags the session on the ledger. Prints one line per finding."""
    issues = board.open_issues()
    if issues is None:
        print("BLIND board unreadable"); return 0
    now = time.time()
    n = 0
    for i in issues:
        # LAW 50 rule 3: a red-alert item (the founder reported it more than once) with nobody
        # on it is paged every tick until claimed. 2026-08-26: the catalogue 404 sat on the
        # board with P0/P1 labels and no owner while he reported it again.
        if RED_LABEL in [l.lower() for l in i.get("labels", [])] and not board.claimed(i):
            print(f"RED crew#{i['number']} red-alert with no owner"); n += 1
            # crew#23: escalate fired 18 times and delivered 0, and nothing said so. A page is
            # either PAGED (send_operator_alert returned True: sent or inboxed, receipt in the
            # telegram ledger) or UNDELIVERED with the reason, on stdout and on the board ledger.
            try:
                from estate import estate_alert as ea
                sent = ea.send_operator_alert(
                    f"RED ALERT crew#{i['number']} has no owner: {i.get('title','')[:80]} "
                    f"https://github.com/{board.REPO}/issues/{i['number']}",
                    debounce_key=f"red-unowned-{i['number']}")
                why = "" if sent else "send_operator_alert returned False (suppressed, no creds, capped or failed)"
            except Exception as exc:
                sent, why = False, f"{type(exc).__name__}: {exc}"[:160]
            print(f"PAGED crew#{i['number']}" if sent else f"UNDELIVERED crew#{i['number']} {why}")
            board.ledger({"guard": "auto-objective", "event": "paged" if sent else "undelivered",
                          "item": i["number"], "why": why})
        cs = i.get("comments", [])
        for k, c in enumerate(cs):
            b = (c.get("body") or "").lstrip()
            if not b.startswith(board.BLOCKED):
                continue
            later = [(x.get("body") or "").lstrip() for x in cs[k + 1:]]
            verdict = next((l for l in later if l.startswith((board.VALID, board.INVALID))), "")
            try:
                age = now - time.mktime(time.strptime(c.get("created_at", "")[:19], "%Y-%m-%dT%H:%M:%S")) + time.timezone
            except Exception:
                age = 0
            if verdict.startswith(board.INVALID):
                board.ledger({"guard": "auto-objective", "event": "rogue_blocker", "item": i["number"]})
                print(f"ROGUE crew#{i['number']} blocker judged INVALID"); n += 1
            elif not verdict and age > BLOCKED_STALE_S:
                print(f"STALE crew#{i['number']} BLOCKED {int(age/60)}m with no VALID:/INVALID:"); n += 1
                try:
                    from estate import estate_alert as ea
                    # Founder, 2026-08-26, after four hours of "nobody validated it" on crew#301:
                    # "how do i know i need to unblock?" The ping carries the action, not the age.
                    ea.send_operator_alert(stale_blocked_text(i["number"], age, b),
                                           debounce_key=f"blocked-stale-{i['number']}")
                except Exception:
                    pass
    print(f"scan: {n} finding(s)")
    return 0


def stale_blocked_text(number: int, age_s: float, blocked_body: str) -> str:
    """The stale-BLOCKED ping is the action, never the age alone (founder, 2026-08-26, crew#301:
    "how do i know i need to unblock?"). Quotes the Need:/Who: lines of the BLOCKED comment; a
    comment without them is named rogue in the ping itself."""
    need = " ".join(l.strip() for l in blocked_body.splitlines() if l.strip().startswith(("Need:", "Who:")))
    return (f"BLOCKED on crew#{number} for {int(age_s/60)}m. {need or 'No Need:/Who: line; the session is rogue.'} "
            f"Reply VALID: or INVALID: on https://github.com/{board.REPO}/issues/{number}")


def selftest() -> int:
    import tempfile
    ok = True
    def ck(label, cond):
        nonlocal ok
        ok = ok and bool(cond); print(("PASS " if cond else "FAIL ") + label)
    d = Path(tempfile.mkdtemp(prefix="autoobj-"))
    fx = d / "fx.json"
    os.environ["ESTATE_BOARD_FIXTURE"] = str(fx)
    gg = _gg(); gg.STATE_DIR = d / "goal"; gg.LEDGER = d / "gl.jsonl"
    board.LEDGER = d / "ledger.jsonl"
    global OFF
    OFF = d / "off"

    def tr(user="", reply=""):
        p = d / f"t{time.time_ns()}.jsonl"
        rows = []
        if user:
            rows.append({"type": "user", "message": {"role": "user", "content": user}})
        if reply:
            rows.append({"type": "assistant", "message": {"role": "assistant",
                                                          "content": [{"type": "text", "text": reply}]}})
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return str(p)

    def run(sess, **kw):
        return decide({"session_id": sess, "transcript_path": tr(**kw)}, gg)

    fx.write_text(json.dumps([{"number": 41, "title": "old item", "labels": [], "assignees": [], "comments": []},
                              {"number": 42, "title": "newer", "labels": [], "assignees": [], "comments": []}]))
    r = run("s1", reply="WORKING: nothing")
    ck("goalless stop is refused and the oldest item is assigned", r and "crew#41" in r["reason"])
    ck("the goal is on disk for goal-guard", gg.read_state("s1")["goal"].startswith("crew#41"))
    ck("the claim comment was posted", "CLAIM " in open(str(fx) + ".posted.jsonl").read())
    r = run("s1", reply="WORKING: still nothing")
    ck("second stop with zero progress is refused again", r and "nothing has been executed" in r["reason"])
    st = gg.read_state("s1"); st["last_progress_at"] = int(time.time()) + 1; gg.write_state("s1", st)
    ck("once progress is on disk the stop is permitted", run("s1", reply="INVENTORY: x") is None)
    r = run("s2", reply="BLOCKED: gh is down")
    ck("a bare BLOCKED: is refused and names the missing fields", r and "Tried:" in r["reason"])
    ck("false blocker is on the ledger", "false_blocker" in board.LEDGER.read_text())
    r = run("s2", reply="BLOCKED: gh down\nTried: gh auth\nError: 401\nNeed: token\nWho: founder")
    ck("a validated BLOCKED: permits the stop", r is None)
    ck("founder STOP clears the goal and permits", run("s1", user="STOP", reply="x") is None
       and gg.read_state("s1")["goal"] == "")
    ck("released claim is posted", "RELEASE " in open(str(fx) + ".posted.jsonl").read())
    fx.write_text("garbage")
    ck("BLIND board permits (fail open)", run("s3", reply="x") is None)
    fx.write_text("[]")
    ck("empty board permits", run("s4", reply="x") is None)
    fx.write_text(json.dumps([{"number": 7, "title": "t", "labels": [], "assignees": [], "comments": []}]))
    OFF.write_text("")
    ck("kill switch permits everything", run("s5", reply="x") is None)
    OFF.unlink()
    ck("a session with no transcript is left alone", decide({"session_id": "s6", "transcript_path": "/nope"}, gg) is None)
    fx.write_text(json.dumps([{"number": 9, "title": "t", "labels": [], "assignees": [], "comments": [
        {"body": "BLOCKED: x", "created_at": "2026-01-01T00:00:00Z"}]}]))
    fx.write_text(json.dumps([{"number": 5, "title": "open work", "labels": [], "assignees": [], "comments": []}]))
    # The cut of 2026-08-28: the trigger is open work, not run count.
    p = tr(reply="WORKING: nothing independent left")
    ck("v2: a run in flight permits the retry, whatever the reply says",
       retry_decision({"transcript_path": p, "session_id": "s7"}, ["live1"]) is None)
    ck("v2: a working session leaves no false_idle row",
       "false_idle" not in board.LEDGER.read_text())
    ck("v2: WAITING: no longer has to name the run",
       retry_decision({"transcript_path": tr(reply="WAITING: for things"), "session_id": "s7"},
                      ["live1"]) is None)
    # ...and the control that keeps the case above from being vacuous: NO open work, unclaimed
    # items on the board. That is the idleness the guard was written for and it is still refused.
    r = retry_decision({"transcript_path": p, "session_id": "s7"}, [])
    ck("v2: retry with NO open work and unclaimed items is refused", r and "crew#5" in r["reason"])
    ck("v2: false_idle is on the ledger", "false_idle" in board.LEDGER.read_text())
    ck("v2: a validated BLOCKED: permits the retry",
       retry_decision({"transcript_path": tr(reply="BLOCKED: x\nTried: a\nError: b\nNeed: c\nWho: d")}, []) is None)
    ck("v2: founder STOP permits the retry", retry_decision({"transcript_path": tr(user="STOP")}, []) is None)
    fx.write_text("[]")
    ck("v2: empty board permits the retry", retry_decision({"transcript_path": p}, []) is None)
    fx.write_text("garbage")
    ck("v2: BLIND board permits (fail open)", retry_decision({"transcript_path": p}, []) is None)
    fx.write_text(json.dumps([{"number": 9, "title": "t", "labels": [], "assignees": [], "comments": [
        {"body": "BLOCKED: x", "created_at": "2026-01-01T00:00:00Z"}]}]))
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): scan()
    ck("scan flags a stale unvalidated BLOCKED", "STALE crew#9" in buf.getvalue())
    os.environ["ESTATE_ALERT_INBOX"] = str(Path(d) / "inbox.jsonl")   # the fixture page never reaches the real inbox
    fx.write_text(json.dumps([
        {"number": 11, "title": "red", "labels": ["red-alert"], "assignees": [], "comments": []},
        {"number": 12, "title": "red owned", "labels": ["red-alert"], "assignees": ["x"], "comments": []}]))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): scan()
    ck("scan pages an unowned red-alert item", "RED crew#11" in buf.getvalue())
    ck("scan leaves an owned red-alert item alone", "RED crew#12" not in buf.getvalue())
    # crew#23 both ways: a page that did not arrive is named, a page that did is a receipt
    import types
    from estate import estate_alert as ea
    real = ea.send_operator_alert
    try:
        ea.send_operator_alert = lambda *a, **k: False
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): scan()
        ck("scan names an undelivered page", "UNDELIVERED crew#11" in buf.getvalue())
        ea.send_operator_alert = lambda *a, **k: True
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): scan()
        ck("scan prints a receipt for a delivered page", "PAGED crew#11" in buf.getvalue())
    finally:
        ea.send_operator_alert = real
    print("PASS auto-objective" if ok else "FAIL auto-objective")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--scan" in sys.argv:
        return scan()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        r = decide(payload)
    except Exception:
        try:
            import guard_report; guard_report.broken(__file__, 0)
        except Exception:
            pass
        return 0
    if r:
        print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
