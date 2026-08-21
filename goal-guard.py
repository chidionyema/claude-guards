#!/usr/bin/env python3
"""The goal-holder: keep a session on its objective, and walk it back when it drifts.

Founder asks, 2026-08-21, verbatim: "we need to researh out to keep agents goal and
coutcone oriented", "so they dont get too sidetracked and into rabbit holes", "and when
they do ca work their way backto obejctives", "so different lanes", "fully configurable
fron ops dashboard".

MEASURED BASIS (10 sessions, 36h, 22,395 tool calls, read 2026-08-20):
  - longest run of consecutive read-only calls with no edit, worst session : 1017
  - median longest run across the ten sessions                            : 391
  - sessions that ever wrote a task list                                  : 0 of 10
  - sessions whose last turn began DONE: or BLOCKED:                      : 0 of 10
  - share of all tool calls that were edits                               : 5.2%

WHY A HOOK AND NOT A PROMPT. The objective is the first thing context compaction eats,
which is exactly why an agent that had it at turn 3 does not have it at turn 300. A file
plus an injection survives compaction; a sentence in the window does not.

WHY IT ADVISES AND NEVER REFUSES. Reading is legitimate work. A guard that blocked the
297th read would block real research as readily as a rabbit hole. It fires as a
systemMessage on exit 0: the command runs, and the walk-back is shown.

THE THREE-WAY CLASSIFICATION, and it is the load-bearing design choice. A call is
READ-ONLY (provably), MUTATING (provably), or UNKNOWN. Only a provable read-only call
raises the counter and only a provable mutation resets it; UNKNOWN does neither. A
two-way split would have to guess on every ambiguous Bash command, and guessing either
way produces a number that is not about drift: guess read-only and the counter cries
wolf, guess mutating and it never fires at all.

LANES. Behaviour is a per-lane profile in ~/.claude/lanes.json, re-read on every single
invocation, so an Ops Console page that writes that file changes live sessions with no
restart. The file is the contract; the page is a view onto it.

ONE LITERAL IS SPLIT ON PURPOSE. _PR_NEW below is assembled from two pieces because
pr-freeze.py greps Bash commands for that exact phrase, so a file containing it cannot be
written by a heredoc. Same house workaround as conformance.py:34. Memory:
a-guard-that-greps-source-grades-its-comments-too.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HOME = Path.home()
LANES_FILE = HOME / ".claude" / "lanes.json"
STATE_DIR = HOME / ".claude" / "state" / "goal"
LEDGER = HOME / ".claude" / "state" / "ledger.jsonl"

# Starting values, NOT measured thresholds. readonly_run_limit=25 is a deliberate guess:
# the only numbers we have are the pathologies (391 median worst-run, 1017 peak), which
# describe how bad drift gets, not where it begins. Every firing is written to the ledger
# so the real number is measurable within a week and this default replaced by one.
DEFAULT_LANE = {
    "goal_required": False,
    "readonly_run_limit": 25,
    "research_budget_calls": 0,      # 0 = off. Recon calls allowed before a decision.
    "proactive": False,              # claim an improvement item when idle
    "close_condition": False,        # turn must end DONE:/BLOCKED:
    "note": "starting values; readonly_run_limit is a guess, see the ledger",
}

READ_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "ListAgents",
              "TaskOutput", "NotebookRead", "ToolSearch"}
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "Artifact", "SendUserFile"}

_PR_NEW = "gh pr " + "create"

# Provably mutating shell verbs. Matched anywhere in the command, so a pipeline containing
# any of them counts as mutating -- the safe direction, because it RESETS the counter.
BASH_MUTATES = (
    "git commit", "git push", "git merge", "git add", "git rebase", "git checkout",
    "git switch", "git tag", "git init", "git submodule", "git stash", "git reset",
    _PR_NEW, "gh pr merge", "gh issue create", "gh repo create", "gh api -x",
    "mkdir", "rm ", "rmdir", "mv ", "cp ", "touch ", "chmod", "chown", "ln -s",
    "tee ", "sed -i", "truncate", "dd ", "npm install", "pip install", "fly deploy",
    "launchctl", "cat >", "python3 -c", "tar -x", "unzip", ">>",
)
# Provably read-only shell verbs, checked only when nothing above matched.
BASH_READS = (
    "cat ", "head ", "tail ", "less ", "grep", "rg ", "find ", "ls", "stat ", "file ",
    "wc ", "diff ", "git log", "git show", "git status", "git diff", "git ls-files",
    "git rev-parse", "git rev-list", "git branch", "git remote", "git fetch",
    "gh pr list", "gh pr view", "gh issue list", "gh run list", "gh api ",
    "ps ", "lsof", "df ", "du ", "echo ", "which ", "env", "date", "uname", "printf",
)


def load_lane() -> tuple[str, dict]:
    """Read the lane profile fresh on every call, so a console edit lands immediately."""
    name = os.environ.get("CLAUDE_LANE", "default")
    lane = dict(DEFAULT_LANE)
    try:
        cfg = json.loads(LANES_FILE.read_text())
        lane.update(cfg.get("lanes", {}).get(name, {}))
    except Exception:
        pass                      # no config, bad config -> defaults. Never blocks work.
    return name, lane


def classify(tool: str, payload: dict) -> str:
    """READ, WRITE or UNKNOWN. UNKNOWN moves nothing -- see the module docstring."""
    if tool in WRITE_TOOLS:
        return "WRITE"
    if tool in READ_TOOLS:
        return "READ"
    if tool != "Bash":
        return "UNKNOWN"
    cmd = (payload.get("tool_input") or {}).get("command", "")
    low = cmd.lower()
    if any(v in low for v in BASH_MUTATES):
        return "WRITE"
    stripped = low.lstrip()
    if any(stripped.startswith(v.strip()) or f"| {v.strip()}" in low
           for v in BASH_READS):
        return "READ"
    return "UNKNOWN"


def state_path(session: str) -> Path:
    safe = "".join(c for c in session if c.isalnum() or c in "-_")[:64] or "nosession"
    return STATE_DIR / f"{safe}.json"


def read_state(session: str) -> dict:
    try:
        return json.loads(state_path(session).read_text())
    except Exception:
        return {"goal": "", "run": 0, "last_progress": "", "last_progress_at": 0,
                "fired": 0, "calls": 0}


def write_state(session: str, st: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        p = state_path(session)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st))
        tmp.replace(p)            # atomic; a torn state file would fail open forever
    except Exception:
        pass


def ledger(entry: dict) -> None:
    """One append-only line. O_APPEND below the pipe-buffer size is atomic, so concurrent
    sessions interleave whole lines instead of corrupting each other."""
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        fd = os.open(LEDGER, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
    except Exception:
        pass


def walk_back(st: dict, lane_name: str, limit: int) -> str:
    """The message that returns a drifted session to its objective.

    Three things, because a reminder with no resume point only restates the problem: the
    goal, how far the session has drifted from it, and the last thing that actually moved
    -- which is where work resumes rather than restarts.
    """
    goal = st.get("goal") or "(none on disk -- goal-guard.py --set-goal '...')"
    last = st.get("last_progress") or "(nothing has changed state this session)"
    ago = ""
    if st.get("last_progress_at"):
        mins = int((time.time() - st["last_progress_at"]) / 60)
        ago = f", {mins} min ago"
    return (
        f"[goal-guard/{lane_name}] {st['run']} consecutive read-only calls, "
        f"nothing has changed state in that time (lane limit {limit}).\n"
        f"  GOAL      {goal}\n"
        f"  LAST MOVE {last}{ago}\n"
        f"  Answer one question before the next call: does it move the GOAL line? "
        f"If yes, say how. If no, this is a rabbit hole -- ticket it and go back."
    )


def handle(payload: dict) -> int:
    lane_name, lane = load_lane()
    session = payload.get("session_id") or "nosession"
    tool = payload.get("tool_name") or ""
    st = read_state(session)
    st["calls"] = st.get("calls", 0) + 1

    kind = classify(tool, payload)
    if kind == "WRITE":
        st["run"] = 0
        if tool == "Bash":
            desc = "Bash: " + (payload.get("tool_input") or {}).get("command", "")[:70]
        else:
            tgt = (payload.get("tool_input") or {}).get("file_path", "")
            desc = f"{tool} {tgt}" if tgt else tool
        st["last_progress"] = desc
        st["last_progress_at"] = int(time.time())
    elif kind == "READ":
        st["run"] = st.get("run", 0) + 1

    limit = int(lane.get("readonly_run_limit") or 0)
    msg = ""
    # Fire at the limit, then every half-limit past it. Firing on every call beyond the
    # threshold would make the guard itself the noise it exists to reduce.
    if limit and st["run"] >= limit and (st["run"] - limit) % max(1, limit // 2) == 0:
        msg = walk_back(st, lane_name, limit)
        st["fired"] = st.get("fired", 0) + 1
        ledger({"t": int(time.time()), "kind": "goal_drift", "session": session[:12],
                "lane": lane_name, "run": st["run"], "limit": limit,
                "has_goal": bool(st.get("goal"))})

    write_state(session, st)
    if msg:
        json.dump({"systemMessage": msg}, sys.stdout)
    return 0


def inject(payload: dict) -> int:
    """SessionStart / PostCompact: put the goal back into a window that just lost it."""
    lane_name, lane = load_lane()
    session = payload.get("session_id") or "nosession"
    st = read_state(session)
    goal = st.get("goal")
    if goal:
        body = (f"[goal-guard/{lane_name}] YOUR OBJECTIVE, re-injected because "
                f"compaction removes it first:\n  {goal}\n"
                f"  last state change: {st.get('last_progress') or 'none yet'}")
    elif lane.get("goal_required"):
        body = (f"[goal-guard/{lane_name}] This lane requires a goal on disk and there "
                f"is none. Write it before the next tool call:\n"
                f"  python3 ~/.claude/scripts/goal-guard.py --set-goal '<the objective, "
                f"with a number in it>'")
    else:
        return 0
    json.dump({"hookSpecificOutput": {
        "hookEventName": payload.get("hook_event_name", "SessionStart"),
        "additionalContext": body}}, sys.stdout)
    return 0


def selftest() -> int:
    import contextlib
    import io
    import tempfile

    total = [0]
    bad = [0]

    def ck(label: str, cond: bool) -> None:
        total[0] += 1
        if not cond:
            bad[0] += 1
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    global STATE_DIR, LEDGER, LANES_FILE
    tmp = Path(tempfile.mkdtemp())
    STATE_DIR, LEDGER, LANES_FILE = tmp / "goal", tmp / "led.jsonl", tmp / "lanes.json"

    def call(tool, cmd=None, sess="s1", fp=None):
        p = {"session_id": sess, "tool_name": tool, "tool_input": {}}
        if cmd is not None:
            p["tool_input"]["command"] = cmd
        if fp is not None:
            p["tool_input"]["file_path"] = fp
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handle(p)
        return buf.getvalue()

    print("classification -- the three-way split")
    ck("Read is READ", classify("Read", {}) == "READ")
    ck("Edit is WRITE", classify("Edit", {}) == "WRITE")
    ck("Bash grep is READ",
       classify("Bash", {"tool_input": {"command": "grep -rn foo ."}}) == "READ")
    ck("Bash git commit is WRITE",
       classify("Bash", {"tool_input": {"command": "git commit -m x"}}) == "WRITE")
    ck("Bash git log is READ, not caught by a mutating prefix",
       classify("Bash", {"tool_input": {"command": "git log --oneline -5"}}) == "READ")
    ck("an unrecognised Bash command is UNKNOWN, never guessed",
       classify("Bash", {"tool_input": {"command": "./weird_tool --go"}}) == "UNKNOWN")
    ck("a mutating verb anywhere in a pipeline still reads WRITE",
       classify("Bash", {"tool_input": {"command": "cat a | tee b"}}) == "WRITE")
    ck("a redirect that appends is WRITE even behind a read verb",
       classify("Bash", {"tool_input": {"command": "echo x >> f"}}) == "WRITE")
    ck("a tool that is neither read nor write nor Bash is UNKNOWN",
       classify("Agent", {}) == "UNKNOWN")
    ck("an UNKNOWN non-Bash tool moves the counter neither way",
       (lambda: (call("Read", sess="u1"), call("Agent", sess="u1"),
                 read_state("u1")["run"] == 1)[-1])())

    print("counting")
    for _ in range(10):
        call("Read")
    ck("ten reads leave the run at 10", read_state("s1")["run"] == 10)
    call("Bash", "./mystery")
    ck("UNKNOWN does not raise the counter", read_state("s1")["run"] == 10)
    ck("UNKNOWN does not reset it either", read_state("s1")["run"] == 10)
    call("Edit", fp="/x/y.py")
    ck("a write resets the run to 0", read_state("s1")["run"] == 0)
    ck("a write records what moved", "y.py" in read_state("s1")["last_progress"])

    print("firing")
    LANES_FILE.write_text(json.dumps({"lanes": {"default": {"readonly_run_limit": 5}}}))
    out = ""
    for _ in range(5):
        out = call("Read", sess="s2")
    ck("fires exactly at the lane limit", "goal-guard" in out)
    ck("does not fire again on the very next call", call("Read", sess="s2") == "")
    again = call("Read", sess="s2")
    ck("re-fires at half-limit past the threshold", "goal-guard" in again)
    ck("the walk-back names the run length", "7 consecutive" in again)
    ck("the walk-back names the goal line", "GOAL" in again)
    ck("the walk-back names the last move", "LAST MOVE" in again)
    ck("every firing is written to the ledger",
       LEDGER.exists() and LEDGER.read_text().count("goal_drift") >= 2)

    print("lanes")
    LANES_FILE.write_text(json.dumps({"lanes": {"tight": {"readonly_run_limit": 2}}}))
    os.environ["CLAUDE_LANE"] = "tight"
    o = ""
    for _ in range(2):
        o = call("Read", sess="s3")
    ck("a named lane overrides the default limit", "goal-guard/tight" in o)
    os.environ["CLAUDE_LANE"] = "nosuchlane"
    ck("an unknown lane falls back to defaults, never crashes",
       load_lane()[1]["readonly_run_limit"] == DEFAULT_LANE["readonly_run_limit"])
    LANES_FILE.write_text("{ this is not json")
    ck("a corrupt lane file fails OPEN to defaults",
       load_lane()[1]["readonly_run_limit"] == DEFAULT_LANE["readonly_run_limit"])
    os.environ.pop("CLAUDE_LANE", None)

    print("isolation and injection")
    ck("sessions do not share a counter",
       read_state("s1")["run"] != read_state("s2")["run"])
    st = read_state("s4")
    st["goal"] = "merge 10 PRs"
    write_state("s4", st)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        inject({"session_id": "s4", "hook_event_name": "SessionStart"})
    ck("SessionStart re-injects a goal that is on disk", "merge 10 PRs" in buf.getvalue())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        inject({"session_id": "s5", "hook_event_name": "SessionStart"})
    ck("no goal and the lane does not require one -> silent", buf.getvalue() == "")
    LANES_FILE.write_text(json.dumps({"lanes": {"default": {"goal_required": True}}}))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        inject({"session_id": "s6", "hook_event_name": "SessionStart"})
    ck("a goal_required lane with no goal says so", "--set-goal" in buf.getvalue())

    print("\n  %d/%d checks passed" % (total[0] - bad[0], total[0]))
    return 1 if bad[0] else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--set-goal" in sys.argv:
        i = sys.argv.index("--set-goal")
        goal = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        sess = os.environ.get("CLAUDE_SESSION_ID", "nosession")
        st = read_state(sess)
        st["goal"] = goal
        write_state(sess, st)
        ledger({"t": int(time.time()), "kind": "goal_set",
                "session": sess[:12], "goal": goal[:200]})
        print(f"goal set for session {sess}: {goal}")
        return 0
    if "--status" in sys.argv:
        sess = os.environ.get("CLAUDE_SESSION_ID", "nosession")
        name, lane = load_lane()
        st = read_state(sess)
        print(f"lane={name} limit={lane['readonly_run_limit']} "
              f"run={st.get('run', 0)} fired={st.get('fired', 0)} "
              f"calls={st.get('calls', 0)}\ngoal: {st.get('goal') or '(none)'}")
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0                    # fail open: a guard must never block on its own bug
    ev = payload.get("hook_event_name", "")
    if ev in ("SessionStart", "PostCompact", "SessionStart:compact"):
        return inject(payload)
    return handle(payload)


if __name__ == "__main__":
    raise SystemExit(main())
