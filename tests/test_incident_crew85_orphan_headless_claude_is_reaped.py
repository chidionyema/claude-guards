"""crew#85 row 2, incident 2026-08-27: pid 2071 `claude -p "Use web search to find evidence about..."`
(prospector/claude_cli.py, cwd prospector_cli_cwd/slot_0) ran for hours at 60-88% of a core with
ppid 1: its caller had been SIGKILLed, so subprocess.run's timeout never fired and nobody read the
output. Rule: runaway-reaper.sh reaps a headless `claude -p` whose parent is gone (ppid 1) and older
than REAPER_CLAUDE_P_MAX_AGE; a `claude -p` whose caller is alive is never matched. Rung 4, both
ways in one run, using a perl symlinked as `claude` so no real Claude process is spawned."""
import os
import re
import signal
import subprocess
import time
from pathlib import Path

REAPER = Path(__file__).resolve().parents[1] / "estate" / "runaway-reaper.sh"


def _dry_run(env_age="0"):
    env = dict(os.environ, REAPER_CLAUDE_P_MAX_AGE=env_age)
    out = subprocess.run(["bash", str(REAPER), "--dry-run"], capture_output=True, text=True, env=env, timeout=60)
    return out.stdout + out.stderr


def test_orphaned_headless_claude_is_matched_and_a_parented_one_is_not(tmp_path):
    fake = tmp_path / "claude"
    fake.symlink_to("/usr/bin/perl")          # `perl -p` blocks on stdin, like a claude -p waiting on the API
    # orphan: double fork so the reader sees ppid 1
    orphan_cmd = f"( {fake} -p < /dev/zero > /dev/null 2>&1 & echo $! > {tmp_path}/orphan.pid ) &"
    subprocess.run(["bash", "-c", orphan_cmd], check=True)
    time.sleep(0.5)
    orphan = int((tmp_path / "orphan.pid").read_text())
    # parented: the same argv with this test as its live parent
    parented = subprocess.Popen([str(fake), "-p"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        out = _dry_run("0")
        matched = {int(m) for m in re.findall(r"would reap pid=(\d+) age=\d+s rule=orphan-headless-claude", out)}
        assert orphan in matched, out
        assert parented.pid not in matched, out
        # the other way for age: with the default hour, a fresh orphan is not touched
        out2 = _dry_run("3600")
        assert f"pid={orphan} " not in out2, out2
    finally:
        for pid in (orphan, parented.pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        parented.wait(timeout=5)
