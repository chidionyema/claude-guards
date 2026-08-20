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

    python3 ~/.claude/scripts/agent-fleet-fence.py --release      # one, the oldest
    python3 ~/.claude/scripts/agent-fleet-fence.py --release-all  # only if you know all are done
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
    print(f"PASS: cap holds at {CAP}, Workflow refused, Bash untouched, leases expire."
          if ok else "SELFTEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--release-all" in sys.argv:
        n = 0
        for f in LEASES.glob("*.lease"):
            f.unlink(missing_ok=True); n += 1
        print(f"released {n} lease(s)"); sys.exit(0)
    if "--release" in sys.argv:
        live = _live()
        if live:
            live[-1][0].unlink(missing_ok=True); print("released 1 lease")
        else:
            print("no live leases")
        sys.exit(0)
    if "--status" in sys.argv:
        live = _live()
        print(f"{len(live)}/{CAP} leases live")
        for f, age in live:
            try: j = json.loads(f.read_text())
            except Exception: j = {}
            print(f"  {int(age)//60}m  {str(j.get('session','?'))[:8]}  {j.get('desc','')}")
        sys.exit(0)
    main()
