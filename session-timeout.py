#!/usr/bin/env python3
"""crew#306 CP3. Every 5 minutes: a session holding a goal that has produced no transcript
output and no recorded progress for 10 minutes is killed, and its board claim is released
so the next goalless session picks the item up.

Founder, 2026-08-26: "Agent cannot 'think' or 'recon' for 10 minutes without shipping."
"24h grace for agents to adapt, then hard." The grace clock starts at the first run, is
written to ~/.claude/state/session-timeout.enforce-after, and until it passes the job only
prints WOULD KILL and posts nothing.

Runs on the Mac by launchd because that is where the sessions are; a session's process is
found by asking lsof who holds its transcript open. No session id in argv, no guessing.

  session-timeout.py            one pass, prints one line per idle session
  session-timeout.py --selftest
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import estate_board as board

HOME = Path(os.path.expanduser("~"))
GOAL_DIR = HOME / ".claude/state/goal"
PROJECTS = HOME / ".claude/projects"
ENFORCE_AFTER = HOME / ".claude/state/session-timeout.enforce-after"
IDLE_S = 600
_SELF_OK = False        # the selftest holds its own fixture open
GRACE_S = 86400


def enforcing(now: float) -> bool:
    try:
        return now >= float(ENFORCE_AFTER.read_text().strip())
    except Exception:
        try:
            ENFORCE_AFTER.parent.mkdir(parents=True, exist_ok=True)
            ENFORCE_AFTER.write_text(str(now + GRACE_S))
        except Exception:
            pass
        return False


def transcript_for(session: str) -> Path | None:
    hits = list(PROJECTS.glob(f"*/{session}.jsonl"))
    return hits[0] if hits else None


def pid_holding(path: Path) -> int | None:
    try:
        out = subprocess.run(["lsof", "-t", str(path)], capture_output=True, text=True, timeout=20)
        pids = [int(x) for x in out.stdout.split() if x.isdigit() and (int(x) != os.getpid() or _SELF_OK)]
        return pids[0] if pids else None
    except Exception:
        return None


def idle_sessions(now: float) -> list[dict]:
    found = []
    for f in GOAL_DIR.glob("*.json"):
        try:
            st = json.loads(f.read_text())
        except Exception:
            continue
        if not st.get("goal") or st.get("blocked_at"):
            continue
        session = f.stem
        t = transcript_for(session)
        if t is None:
            continue
        quiet = now - max(t.stat().st_mtime, float(st.get("last_progress_at", 0) or 0))
        if quiet < IDLE_S:
            continue
        pid = pid_holding(t)
        if pid is None:
            continue                       # nobody has it open: the session already ended
        found.append({"session": session, "goal": st["goal"], "quiet_s": int(quiet), "pid": pid,
                      "item": board.goal_number(st["goal"]), "state_file": f, "transcript": t})
    return found


def act(row: dict, enforce: bool, kill=os.kill) -> str:
    if not enforce:
        board.ledger({"guard": "session-timeout", "event": "would_kill", "session": row["session"][:8],
                      "quiet_s": row["quiet_s"], "item": row["item"]})
        return f"WOULD KILL session {row['session'][:8]} pid {row['pid']} quiet {row['quiet_s']//60}m goal {row['goal'][:50]}"
    event = "killed"
    try:
        kill(row["pid"], signal.SIGTERM)
    except ProcessLookupError:
        # crew#306 CP3, 2026-08-27: the first enforce hits were `FAILED kill 9f8f4f5f pid 72761`
        # and later `pid 8338` for the same session -- lsof names whoever has the transcript open
        # at that instant, and a transient reader can be gone by kill time. Re-resolve; a
        # transcript nobody holds means the session ended, and its claim is released the same
        # way a kill releases it. Before this the claim stayed held and nothing reached the ledger.
        again = pid_holding(row["transcript"]) if row.get("transcript") else None
        if again and again != row["pid"]:
            try:
                kill(again, signal.SIGTERM)
            except Exception as e:
                board.ledger({"guard": "session-timeout", "event": "kill_failed", "session": row["session"][:8],
                              "pid": again, "error": str(e), "item": row["item"]})
                return f"FAILED kill {row['session'][:8]} pid {again}: {e}"
            row["pid"] = again
        else:
            event = "ended"
    except Exception as e:
        board.ledger({"guard": "session-timeout", "event": "kill_failed", "session": row["session"][:8],
                      "pid": row["pid"], "error": str(e), "item": row["item"]})
        return f"FAILED kill {row['session'][:8]} pid {row['pid']}: {e}"
    try:
        st = json.loads(row["state_file"].read_text())
        st["goal"] = ""; st["released_by_timeout_at"] = int(time.time())
        row["state_file"].write_text(json.dumps(st))
    except Exception:
        pass
    if row["item"]:
        board.release(row["item"], row["session"], f"session-timeout: no output for {row['quiet_s']//60}m")
    board.ledger({"guard": "session-timeout", "event": event, "session": row["session"][:8],
                  "quiet_s": row["quiet_s"], "item": row["item"]})
    verb = "KILLED" if event == "killed" else "ENDED"
    return f"{verb} session {row['session'][:8]} pid {row['pid']} quiet {row['quiet_s']//60}m; crew#{row['item']} released"


def run() -> int:
    now = time.time()
    enforce = enforcing(now)
    rows = idle_sessions(now)
    for r in rows:
        print(act(r, enforce))
    print(f"session-timeout: {len(rows)} idle session(s), mode={'enforce' if enforce else 'report'}")
    return 0


def selftest() -> int:
    import tempfile
    global GOAL_DIR, PROJECTS, ENFORCE_AFTER, _SELF_OK
    _SELF_OK = True
    ok = True
    def ck(label, cond):
        nonlocal ok
        ok = ok and bool(cond); print(("PASS " if cond else "FAIL ") + label)
    d = Path(tempfile.mkdtemp(prefix="sto-"))
    GOAL_DIR = d / "goal"; PROJECTS = d / "projects"; ENFORCE_AFTER = d / "enforce"
    GOAL_DIR.mkdir(); (PROJECTS / "slug").mkdir(parents=True)
    fx = d / "fx.json"; fx.write_text("[]"); os.environ["ESTATE_BOARD_FIXTURE"] = str(fx)
    board.LEDGER = d / "ledger.jsonl"
    now = time.time()
    ck("first run starts the 24h grace and does not enforce", not enforcing(now) and ENFORCE_AFTER.exists())
    ck("after the grace it enforces", enforcing(now + GRACE_S + 1))

    def session(name, goal, age_s, hold):
        (GOAL_DIR / f"{name}.json").write_text(json.dumps({"goal": goal, "last_progress_at": 0}))
        t = PROJECTS / "slug" / f"{name}.jsonl"; t.write_text("{}\n")
        os.utime(t, (now - age_s, now - age_s))
        return open(t) if hold else None

    h1 = session("idle1", "crew#41: x", 900, True)        # held open, quiet 15m -> idle
    session("gone1", "crew#42: x", 900, False)            # nobody holds it -> already ended
    h3 = session("busy1", "crew#43: x", 60, True)         # quiet 1m -> fine
    (GOAL_DIR / "nogoal.json").write_text(json.dumps({"goal": ""}))
    rows = idle_sessions(now)
    ck("only the held, quiet session is idle", [r["session"] for r in rows] == ["idle1"])
    ck("report mode says WOULD KILL and kills nothing",
       act(rows[0], False, kill=lambda *a: (_ for _ in ()).throw(AssertionError("killed"))).startswith("WOULD KILL"))
    killed = []
    msg = act(rows[0], True, kill=lambda pid, sig: killed.append(pid))
    ck("enforce mode kills the pid and releases the claim", killed == [rows[0]["pid"]] and "released" in msg
       and "RELEASE " in open(str(fx) + ".posted.jsonl").read())
    ck("the goal is cleared so the item is back on the board", json.loads((GOAL_DIR / "idle1.json").read_text())["goal"] == "")
    ck("both outcomes are on the ledger", "would_kill" in board.LEDGER.read_text() and '"killed"' in board.LEDGER.read_text())
    h1.close()
    # crew#306 CP3: the pid lsof named is gone by kill time and nobody holds the transcript
    dead = {"session": "idle1", "goal": "crew#41: x", "quiet_s": 900, "pid": 4_000_000, "item": 41,
            "state_file": GOAL_DIR / "idle1.json", "transcript": PROJECTS / "slug" / "idle1.jsonl"}
    (GOAL_DIR / "idle1.json").write_text(json.dumps({"goal": "crew#41: x", "last_progress_at": 0}))
    def gone(pid, sig):
        raise ProcessLookupError(3, "No such process")
    msg = act(dead, True, kill=gone)
    ck("a pid that vanished before the kill is ENDED, the claim released, the goal cleared",
       msg.startswith("ENDED") and json.loads((GOAL_DIR / "idle1.json").read_text())["goal"] == ""
       and '"ended"' in board.LEDGER.read_text())
    def denied(pid, sig):
        raise PermissionError(1, "Operation not permitted")
    msg = act(dict(dead, pid=4_000_001), True, kill=denied)
    ck("any other kill failure is refused and lands on the ledger", msg.startswith("FAILED") and '"kill_failed"' in board.LEDGER.read_text())
    h3.close()
    print("PASS session-timeout" if ok else "FAIL session-timeout")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else run())
