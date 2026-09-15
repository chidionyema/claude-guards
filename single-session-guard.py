#!/usr/bin/env python3
"""single-session-guard.py -- enforce the 2026-09-08 standing rule: only one interactive
Claude Code session at a time.

Founder, 2026-09-08: "claude code is actually the biggest liability and risk, expensive slow
and never gets things done... a standing rule is only one claude code session allowed."
Recorded at ~/.claude/docs/founder/2026-09-08T1740Z-standing-rule-only-one-claude-code-session-
allowed-c807cd20.md, whose own text names the exact gap this closes: "Until that guard lands,
any session that finds another running names its pid in its first reply and does not start
parallel work." No session ever built the guard -- sessions kept naming pids and continuing
anyway. Found the hard way, 2026-09-15: five `claude` processes running on one machine, one of
them rebased a shared branch mid-edit and briefly wiped a second session's uncommitted work
(feat/mutation-ledger-backstage-door, git reflog c6488c8c).

WHAT THIS DOES: on SessionStart with source=="startup" (a genuinely new session -- never on
resume/clear/compact, which are the SAME session continuing, not a second one), count other
top-level `claude` CLI processes already running. One or more found -> refuse (exit 2), naming
every pid, exactly the protocol the incident record already describes but nothing enforced.

FAILS OPEN, NEVER CLOSED. `ps` unreadable, unparseable, or this session's own process not
findable among the matches -> let the session start. A guard that can lock the founder out of
every session over its own bug is a worse outage than the one it prevents -- hook-run.py's own
doctrine, LAW 38: "a measurement that breaks the thing it measures is an outage."

EXCLUDED, deliberately: `claude --chrome-native-host` (a Chrome extension's messaging host, not
an interactive session) and anything that merely contains the substring "claude" in a longer
path (`.claude/scripts/*.py`, `chroma-mcp`, `claude-mem`'s worker) -- matched by requiring the
process's own comm basename to be exactly `claude`, not a substring match.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

EXCLUDED_FLAGS = {"--chrome-native-host"}


def list_claude_pids(run=subprocess.run) -> "list[tuple[int, int, str]] | None":
    """(pid, ppid, full command) for every top-level `claude` CLI process. None means `ps`
    itself could not be read -- distinct from an empty, genuinely-checked list."""
    try:
        proc = run(
            ["ps", "-axo", "pid=,ppid=,comm=,command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid_s, ppid_s, comm, command = parts
        if not (pid_s.isdigit() and ppid_s.isdigit()):
            continue
        if os.path.basename(comm) != "claude":
            continue
        if EXCLUDED_FLAGS & set(command.split()):
            continue
        out.append((int(pid_s), int(ppid_s), command))
    return out


def own_session_pid(
    procs: "list[tuple[int, int, str]]", run=subprocess.run
) -> "int | None":
    """Walk this hook process's own ancestry up to the nearest pid also present in `procs` --
    that is the claude session that invoked this hook (this process -> hook-run.py -> claude,
    normally two hops), always excluded from the "other sessions" count even though it is,
    correctly, one of the raw matches."""
    by_pid = {pid for pid, _, _ in procs}
    pid = os.getpid()
    for _ in range(10):  # generous ceiling; real chain is ~2 hops
        if pid in by_pid:
            return pid
        try:
            proc = run(
                ["ps", "-o", "ppid=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        out = proc.stdout.strip()
        if proc.returncode != 0 or not out.isdigit():
            return None
        pid = int(out)
    return None


def main(stdin=sys.stdin) -> int:
    try:
        payload = json.load(stdin)
    except (ValueError, OSError):
        return 0  # can't read the event at all -- fail open, same doctrine as every guard here
    if payload.get("source") != "startup":
        return 0  # resume/clear/compact are the SAME session continuing, never a second one

    procs = list_claude_pids()
    if procs is None:
        return 0  # blind -- never block on a guess

    me = own_session_pid(procs)
    others = [(pid, cmd) for pid, _, cmd in procs if pid != me]
    if not others:
        return 0

    names = ", ".join(f"{pid} ({cmd.strip()})" for pid, cmd in others)
    print(
        "REFUSED: standing rule (2026-09-08, founder) allows only one Claude Code session. "
        f"Already running: {names}. Close it first, or if this one is genuinely meant to run "
        "alongside it, that is the founder's call to make explicitly here, not this guard's to "
        "assume away.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
