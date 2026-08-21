#!/usr/bin/env python3
"""Refuse a fourth concurrent subagent.

Founder directive 2026-08-20: "we dont hsve th erresources for so nay agents we ned to ske it
inpossible to spin up so nay agents risky to the business resourcesss", "nainun of 4 gents",
then the clarification that decides the number: "capped at addtional agents so 4 in toal
includng u". The main loop counts as one, so THREE subagents is the cap.

What produced it: one session launched twenty background research agents at once and hit the
harness's own concurrency limit of 20. Each agent bills its own tokens. Twenty of them is a
business expense the founder never approved, and no session can see another session's agents,
so "I will only run three" is not a mechanism.

HOW IT COUNTS. A PreToolUse hook fires before the agent starts. There is no reliable signal
that a BACKGROUND agent has finished: the Agent tool returns as soon as the agent is spawned,
so releasing a lease on PostToolUse would release it while the agent is still running and still
spending. So this fence grants a LEASE that expires on a timer, and counts unexpired leases.

That makes it a rate cap as well as a concurrency cap: at most CAP launches per TTL seconds,
machine-wide, across every session. Deliberate. An agent that finished early still holds its
lease, which over-counts; the alternative under-counts, and under-counting is the failure the
founder just paid for.

There IS an honest early release, and an agent should use it: when a task-notification says an
agent has completed, hand its lease back.

    python3 ~/.claude/scripts/agent-fleet-fence.py --release      # the oldest of YOURS
    python3 ~/.claude/scripts/agent-fleet-fence.py --release-all  # all of YOURS, none of theirs
    python3 ~/.claude/scripts/agent-fleet-fence.py --status

Prove it: python3 ~/.claude/scripts/agent-fleet-fence.py --selftest
"""
import json, os, sys, time, uuid, pathlib, tempfile

CAP = 3                 # the founder's four, minus the main loop
TTL = 20 * 60           # seconds a lease is assumed to cover a live agent
LEASES = pathlib.Path(os.environ.get("AGENT_FLEET_DIR",
                                     os.path.expanduser("~/.claude/state/agent-leases")))

# Tools that spawn subagents. Workflow is refused outright rather than leased, because one
# Workflow call can spawn dozens of agents from a script and the count is decided inside that
# script, where this hook cannot see it.
SPAWNERS = {"Agent", "Task"}
FLEETS = {"Workflow"}


def _live():
    """Unexpired leases, pruning expired ones as it goes."""
    LEASES.mkdir(parents=True, exist_ok=True)
    now, out = time.time(), []
    for f in LEASES.glob("*.lease"):
        try:
            age = now - f.stat().st_mtime
        except FileNotFoundError:
            continue
        if age > TTL:
            f.unlink(missing_ok=True)
        else:
            out.append((f, age))
    return sorted(out, key=lambda x: x[1])


def _grant(session, desc):
    LEASES.mkdir(parents=True, exist_ok=True)
    p = LEASES / f"{uuid.uuid4().hex}.lease"
    p.write_text(json.dumps({"session": session, "desc": desc, "t": time.time()}))
    return p


def _deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def main():
    try:
        ev = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = ev.get("tool_name", "")
    if tool in FLEETS:
        _deny(f"The {tool} tool is refused. One workflow script can spawn dozens of agents in a "
              f"single call, and the cap is {CAP} subagents plus the main loop (founder "
              f"directive 2026-08-20, enforced by ~/.claude/scripts/agent-fleet-fence.py). "
              f"Do the work in this session, or launch at most {CAP} Agent calls.")
    if tool not in SPAWNERS:
        sys.exit(0)

    live = _live()
    if len(live) >= CAP:
        oldest = live[-1][1] if live else 0
        _deny(
            f"Agent fleet cap: {len(live)} of {CAP} leases are live, so this agent is refused. "
            f"Every subagent bills its own tokens and no session can see another session's "
            f"agents, which is why this is a machine and not a note (founder directive "
            f"2026-08-20: four agents in total, including the main loop). A lease expires "
            f"{TTL // 60} minutes after it is granted; the oldest has "
            f"{max(0, TTL - int(oldest)) // 60} minutes left. Wait for one, do the work here, "
            f"or — when a task-notification tells you an agent has FINISHED — hand its lease "
            f"back with `python3 ~/.claude/scripts/agent-fleet-fence.py --release`.")

    ti = ev.get("tool_input") or {}
    _grant(ev.get("session_id", "?"),
           str(ti.get("description") or ti.get("subagent_type") or "")[:120])
    sys.exit(0)


def selftest():
    import subprocess
    d = pathlib.Path(tempfile.mkdtemp()) / "leases"
    env = {**os.environ, "AGENT_FLEET_DIR": str(d)}
    ok = True

    def run(payload):
        r = subprocess.run([sys.executable, __file__], input=json.dumps(payload),
                           capture_output=True, text=True, env=env)
        return r.stdout.strip()

    agent = {"tool_name": "Agent", "session_id": "s1", "tool_input": {"description": "x"}}
    for i in range(CAP):
        out = run(agent)
        if out:
            print(f"FAIL: agent {i + 1} of {CAP} was refused: {out}"); ok = False
    out = run(agent)
    if "cap" not in out.lower():
        print(f"FAIL: agent {CAP + 1} was allowed through: {out!r}"); ok = False
    out = run({"tool_name": "Workflow", "session_id": "s1", "tool_input": {}})
    if "refused" not in out.lower():
        print(f"FAIL: Workflow was allowed through: {out!r}"); ok = False
    out = run({"tool_name": "Bash", "session_id": "s1", "tool_input": {}})
    if out:
        print(f"FAIL: Bash was fenced: {out!r}"); ok = False
    for f in d.glob("*.lease"):
        os.utime(f, (time.time() - TTL - 5,) * 2)
    out = run(agent)
    if out:
        print(f"FAIL: an expired lease did not free a slot: {out}"); ok = False
    # A SESSION MAY NEVER RELEASE ANOTHER SESSION'S LEASE. This is graded directly -- the store
    # is inspected for the OTHER session's file by owner, not by counting how many leases remain,
    # because a count cannot tell whose was deleted and that is the whole failure.
    for f in d.glob("*.lease"):
        f.unlink()
    _g = {**env, "CLAUDE_SESSION_ID": "s1"}
    subprocess.run([sys.executable, __file__], input=json.dumps(agent),
                   capture_output=True, text=True, env=_g)
    other = {"tool_name": "Agent", "session_id": "s2", "tool_input": {"description": "theirs"}}
    subprocess.run([sys.executable, __file__], input=json.dumps(other),
                   capture_output=True, text=True, env={**env, "CLAUDE_SESSION_ID": "s2"})

    def owners():
        return sorted(json.loads(f.read_text())["session"] for f in d.glob("*.lease"))

    r = subprocess.run([sys.executable, __file__, "--release"], capture_output=True,
                       text=True, env={**env, "CLAUDE_SESSION_ID": "s2"})
    if owners() != ["s1"]:
        print(f"FAIL: --release by s2 left {owners()}, expected only s1's lease"); ok = False
    # And with no session id it must release NOTHING rather than guess.
    _blind = {k: v for k, v in env.items() if k != "CLAUDE_SESSION_ID"}
    subprocess.run([sys.executable, __file__, "--release-all"], capture_output=True,
                   text=True, env=_blind)
    if owners() != ["s1"]:
        print(f"FAIL: --release-all with no session id released s1's lease"); ok = False

    print(f"PASS: cap holds at {CAP}, Workflow refused, Bash untouched, leases expire."
          if ok else "SELFTEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    # RELEASE IS SESSION-SCOPED. It did not used to be, and that was a defect that made the
    # documented advice actively harmful: `_live()` sorts by age ASCENDING, so `live[-1]` is the
    # OLDEST lease on the machine -- and your own is always the NEWEST. Every session that
    # followed the docstring and "handed its lease back" therefore deleted somebody else's,
    # while its own kept counting. Measured 2026-08-21: two leases belonging to another live
    # session were released this way in one command, and the store said 1/3 while four agents
    # were running. `--release-all` was worse: it deleted every lease on the machine, and its
    # own help text said "only if you know all are done", which no session can ever know about
    # another session's agents.
    if "--release-all" in sys.argv or "--release" in sys.argv:
        me = os.environ.get("CLAUDE_SESSION_ID", "")
        if not me:
            # Fail SAFE, which here means releasing nothing. Under-counting the fleet is the
            # failure the founder already paid for.
            print("refused: CLAUDE_SESSION_ID is not set, so this cannot tell which leases are "
                  "yours. Releasing nothing. Expired leases are pruned automatically.")
            sys.exit(1)
        mine = [(f, age) for f, age in _live()
                if (json.loads(f.read_text()) if f.exists() else {}).get("session") == me]
        if not mine:
            print("no live leases of yours"); sys.exit(0)
        if "--release-all" in sys.argv:
            for f, _ in mine:
                f.unlink(missing_ok=True)
            print(f"released {len(mine)} lease(s) of yours"); sys.exit(0)
        mine[-1][0].unlink(missing_ok=True)      # the oldest of MINE
        print("released 1 lease of yours"); sys.exit(0)
    if "--status" in sys.argv:
        live = _live()
        print(f"{len(live)}/{CAP} leases live")
        for f, age in live:
            try: j = json.loads(f.read_text())
            except Exception: j = {}
            print(f"  {int(age)//60}m  {str(j.get('session','?'))[:8]}  {j.get('desc','')}")
        sys.exit(0)
    main()
