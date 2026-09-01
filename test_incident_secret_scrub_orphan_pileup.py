"""2026-08-31: 38 orphaned secret-scrub.py processes (ppid 1, hours old) took the founder's
Mac to load average 854. settings' 30 s hook timeout killed hook-run.py but never its child;
the orphan kept scanning gigabytes of transcripts and every later Stop started another.

The fix is two guards inside the script itself, because an orphan has no parent left to kill
it: an exclusive flock so a second copy exits at once, and a SIGALRM deadline so a cut-short
pass dies on its own clock. This pins both, deterministically -- the lock by holding it and
running the script, the deadline by reading the parsed value, never by racing a timer."""

from __future__ import annotations

import fcntl
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parent / "secret-scrub.py"


def test_second_copy_exits_at_once_when_the_lock_is_held(tmp_path):
    lock = pathlib.Path.home() / ".claude" / "state" / "secret-scrub.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    assert r.returncode == 0
    assert "another scrub holds the lock" in r.stderr


def test_deadline_comes_from_the_environment_and_arms_before_main():
    src = SCRIPT.read_text()
    assert 'os.environ.get("SECRET_SCRUB_DEADLINE"' in src
    assert "signal.alarm(int(DEADLINE))" in src
    # The alarm must be armed inside __main__ before main() runs, or an orphan
    # mid-scan never hears it.
    tail = src[src.index('if __name__ == "__main__"') :]
    assert tail.index("signal.alarm") < tail.index("sys.exit(main())")
