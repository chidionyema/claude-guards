#!/usr/bin/env python3
"""Incident test: `launchctl kickstart -k` SIGKILLs the daemon, the playwright
node driver survives as an orphan holding the profile, and the next boot dies
with `write EPIPE`. Measured 2026-08-22 on ai.estate.kimi-bridge.

Rung 4 of the ladder in ~/.claude/AGENTS.md: one test per bug, named for the
bug, asserting the rule rather than the code.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="reap-test-"))
os.environ["BRIDGE_HOME"] = str(HOME)
os.environ["BRIDGE_PORT"] = "8798"
sys.path.insert(0, str(Path.home() / ".claude" / "scripts"))
import kimi_bridge as kb  # noqa: E402

FAILED = []


def check(name, ok):
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        FAILED.append(name)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def spawn_leader():
    """A sleeper in its own process group, standing in for the dead daemon,
    with a child standing in for the orphaned node driver."""
    p = subprocess.Popen(
        [sys.executable, "-c",
         "import os,subprocess,sys,time;"
         "subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)']);"
         "time.sleep(300)"],
        start_new_session=True)
    time.sleep(1.5)
    return p


# --- the orphan is killed -----------------------------------------------
p = spawn_leader()
kb.PIDFILE.parent.mkdir(parents=True, exist_ok=True)
kb.PIDFILE.write_text(str(p.pid))
kb.reap_stale_driver()
# p is our own child, so it lingers as a zombie until it is waited on and
# os.kill(pid, 0) still succeeds. wait() is the honest signal here.
rc = p.wait(timeout=5)
check("a stale process group from the last run is killed", rc == -signal.SIGKILL)

# --- no pidfile is the clean case, not an error -------------------------
kb.PIDFILE.unlink(missing_ok=True)
try:
    kb.reap_stale_driver()
    check("a missing pidfile is the clean shutdown case, not a crash", True)
except Exception as e:
    check(f"a missing pidfile is the clean shutdown case, not a crash ({e})", False)

# --- a pidfile naming a dead process is not an error --------------------
kb.PIDFILE.write_text(str(p.pid))
try:
    kb.reap_stale_driver()
    check("a pidfile naming a dead group is not a crash", True)
except Exception as e:
    check(f"a pidfile naming a dead group is not a crash ({e})", False)

# --- it never kills the running daemon itself ---------------------------
kb.PIDFILE.write_text(str(os.getpid()))
kb.reap_stale_driver()
check("it refuses to kill the process that is doing the reaping",
      alive(os.getpid()))

kb.PIDFILE.write_text(str(os.getpgrp()))
kb.reap_stale_driver()
check("it refuses to kill its own process group", alive(os.getpid()))

print(f"\n{5 - len(FAILED)}/5 green")
sys.exit(1 if FAILED else 0)
