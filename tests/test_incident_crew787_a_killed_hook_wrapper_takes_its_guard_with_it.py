"""crew#787 (2026-09-01): hook-run.py waited 120 s for its guard while settings.json gave the
harness 10 to 60 s per hook, so the harness killed the wrapper and the guard lived on with no
parent. Nine orphaned secret-scrub.py runs, each re-reading 844 MB of transcripts, drove the
founder's Mac to load average 760 and made every local test timing a lie. Rules: a guard never
outlives its wrapper (timeout or signal); the wrapper's budget sits under the harness's; the
scrub reads a live transcript from where it stopped last time.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RUN = HERE / "hook-run.py"
SCRUB = HERE / "secret-scrub.py"

# A guard that records its pid, then hangs; a grandchild it forks does the same.
HANG = """
import os, subprocess, sys, time
sys.stdin.read()
open(sys.argv[1], "w").write(str(os.getpid()))
subprocess.Popen([sys.executable, "-c",
    "import os,sys,time; open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(120)",
    sys.argv[1] + ".grandchild"])
time.sleep(120)
"""
PAYLOAD = json.dumps({"hook_event_name": "Stop", "session_id": "abcdef0123"})


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def _wait_file(path: Path, seconds: float = 20.0) -> int:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.exists() and path.read_text().strip():
            return int(path.read_text().strip())
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def _start(tmp_path: Path, **env) -> tuple[subprocess.Popen, Path]:
    hook = tmp_path / "hang.py"
    hook.write_text(HANG)
    pidfile = tmp_path / "pid"
    # The payload comes from a file, not a pipe: closing a pipe by hand and then calling
    # communicate() is "I/O operation on closed file" on Python 3.12 (the CI runner).
    payload = tmp_path / "payload.json"
    payload.write_text(PAYLOAD)
    with open(payload) as stdin:
        proc = subprocess.Popen(
            [sys.executable, str(RUN), str(hook), str(pidfile)],
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "HOOK_OUTCOMES": str(tmp_path / "ledger.jsonl"), **env},
        )
    return proc, pidfile


def _kill_quietly(*pids: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_the_guard_and_its_grandchild_die_when_the_harness_kills_the_wrapper(tmp_path):
    proc, pidfile = _start(tmp_path, HOOK_TIMEOUT="60")
    guard = _wait_file(pidfile)
    grandchild = _wait_file(Path(str(pidfile) + ".grandchild"))
    try:
        assert _alive(guard) and _alive(grandchild)
        proc.send_signal(signal.SIGTERM)  # what the harness does at its timeout
        out, _err = proc.communicate(timeout=10)
        assert proc.returncode == 2, (proc.returncode, out)
        assert json.loads(out)["decision"] == "block"
        assert _wait_gone(guard), "the guard outlived its wrapper (the crew#787 orphan)"
        assert _wait_gone(grandchild), "the guard's own child outlived the wrapper"
    finally:
        _kill_quietly(guard, grandchild)


def test_the_guard_and_its_grandchild_die_when_the_wrapper_times_out(tmp_path):
    proc, pidfile = _start(tmp_path, HOOK_TIMEOUT="1")
    guard = _wait_file(pidfile)
    grandchild = _wait_file(Path(str(pidfile) + ".grandchild"))
    try:
        out, _err = proc.communicate(timeout=20)
        assert (
            proc.returncode == 2 and "no verdict inside 1s" in json.loads(out)["reason"]
        )
        assert _wait_gone(guard) and _wait_gone(grandchild)
    finally:
        _kill_quietly(guard, grandchild)


def test_the_wrapper_budget_sits_under_the_settings_timeout(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "timeout": 3,
                                    "command": "python3 $HOME/.claude/scripts/hook-run.py $HOME/.claude/scripts/hang.py",
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )
    env = {k: v for k, v in os.environ.items() if k != "HOOK_TIMEOUT"}
    hook = tmp_path / "hang.py"
    hook.write_text(HANG)
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(RUN), str(hook), str(tmp_path / "pid")],
        input=PAYLOAD,
        text=True,
        capture_output=True,
        timeout=30,
        env={
            **env,
            "HOOK_SETTINGS": str(settings),
            "HOOK_OUTCOMES": str(tmp_path / "ledger.jsonl"),
        },
    )
    took = time.monotonic() - t0
    _kill_quietly(
        *[int(p.read_text()) for p in tmp_path.glob("pid*") if p.read_text().strip()]
    )
    assert (
        proc.returncode == 2
        and "no verdict inside 1s" in json.loads(proc.stdout)["reason"]
    )
    assert took < 3, f"the wrapper waited {took:.1f}s, longer than the harness's 3s"


# --- the scrub reads only what was appended since its last run ---------------------------

SECRET = "sk-ant-api03-" + "Q" * 40


def _scrub(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRUB), *args],
        text=True,
        capture_output=True,
        timeout=60,
        env={
            **os.environ,
            "HOME": str(home),
            "SECRET_SCRUB_OFFSETS": str(home / "offsets.json"),
        },
    )


def test_the_second_scrub_reads_only_the_appended_tail(tmp_path):
    home = tmp_path / "home"
    project = home / ".claude" / "projects" / "-Users-x-dev"
    project.mkdir(parents=True)
    transcript = project / "abc.jsonl"
    transcript.write_text(json.dumps({"t": SECRET}) + "\n" + ("x" * 100_000 + "\n") * 5)
    first = _scrub(home)
    assert first.returncode == 0 and "scrubbed 1 occurrence" in first.stdout, (
        first.stdout
    )
    assert SECRET not in transcript.read_text()
    offsets = json.loads((home / "offsets.json").read_text())
    assert offsets[str(transcript)] == transcript.stat().st_size

    # Plant one before the recorded offset (by hand, as no writer would) and append one.
    # Only the appended one is read: the scrub trusts its own record of what it has covered.
    data = bytearray(transcript.read_bytes())
    data[200_000 : 200_000 + len(SECRET)] = SECRET.encode()
    transcript.write_bytes(bytes(data))
    with open(transcript, "a") as fh:
        fh.write(json.dumps({"t": SECRET}) + "\n")
    second = _scrub(home)
    assert "scrubbed 1 occurrence" in second.stdout, second.stdout
    body = transcript.read_bytes()
    assert body[200_000 : 200_000 + len(SECRET)] == SECRET.encode()  # not read again
    assert SECRET.encode() not in body[500_000:]  # the tail was

    # --full reads everything and takes the planted one; so does a file that shrank.
    full = _scrub(home, "--full")
    assert "scrubbed 1 occurrence" in full.stdout, full.stdout
    assert SECRET.encode() not in transcript.read_bytes()
    transcript.write_text(json.dumps({"t": SECRET}) + "\n")
    shrunk = _scrub(home)
    assert "scrubbed 1 occurrence" in shrunk.stdout, shrunk.stdout
    assert SECRET not in transcript.read_text()


def test_a_missing_or_broken_offsets_file_means_a_full_scan_not_a_skipped_one(tmp_path):
    home = tmp_path / "home"
    project = home / ".claude" / "projects" / "-Users-x-dev"
    project.mkdir(parents=True)
    transcript = project / "abc.jsonl"
    transcript.write_text(json.dumps({"t": SECRET}) + "\n")
    (home / "offsets.json").write_text("{not json")
    out = _scrub(home)
    assert "scrubbed 1 occurrence" in out.stdout, out.stdout
    assert SECRET not in transcript.read_text()
