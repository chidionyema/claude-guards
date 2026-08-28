"""crew#603 CP2 (founder, 2026-08-28: "The Mac must pull the latest code from main on every single
session start"). Measured 22:4xZ the same day: the live checkout was 33 commits behind origin/main,
so cg#207's fail-closed door was merged and not running. Rules: a clean checkout fast-forwards at
SessionStart; a locally edited file in the fast-forward's path is named and nothing is reset; a
local edit outside the path does not stop the sync; a dead remote is BLIND, never a crash, and
never a blocked session.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
GUARD = HERE / "sync-guard.py"
RUN = HERE / "hook-run.py"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], text=True, capture_output=True, check=True).stdout.strip()


def _estate(tmp: Path):
    """A bare origin with main, a clone (the Mac), and one commit on origin the clone lacks."""
    origin = tmp / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], check=True)
    seed = tmp / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True)
    _git(seed, "config", "user.email", "t@t"); _git(seed, "config", "user.name", "t")
    (seed / "rule-guard.py").write_text("v1\n"); (seed / "other.py").write_text("o1\n")
    _git(seed, "add", "."); _git(seed, "commit", "-qm", "v1"); _git(seed, "push", "-q", "origin", "main")
    mac = tmp / "mac"
    subprocess.run(["git", "clone", "-q", str(origin), str(mac)], check=True)
    (seed / "rule-guard.py").write_text("v2\n"); _git(seed, "commit", "-qam", "v2"); _git(seed, "push", "-q", "origin", "main")
    return mac, _git(seed, "rev-parse", "--short", "HEAD")


def _run(mac: Path, **env):
    proc = subprocess.run([sys.executable, str(GUARD)], text=True, capture_output=True, input="{}",
                          env={**os.environ, "SYNC_GUARD_DIR": str(mac), **env})
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return proc.stdout


def test_clean_checkout_fast_forwards(tmp_path):
    mac, v2 = _estate(tmp_path)
    text = _run(mac)
    assert "synced" in text and v2 in text, text
    assert (mac / "rule-guard.py").read_text() == "v2\n"
    assert "ok" in _run(mac)


def test_colliding_local_edit_is_named_and_nothing_is_reset(tmp_path):
    mac, _ = _estate(tmp_path)
    (mac / "rule-guard.py").write_text("someone else's edit\n")
    text = _run(mac)
    assert "BLOCKED" in text and "rule-guard.py" in text and "1 behind" in text, text
    assert (mac / "rule-guard.py").read_text() == "someone else's edit\n"
    assert _git(mac, "rev-list", "--count", "HEAD..origin/main") == "1"


def test_local_edit_outside_the_path_does_not_stop_the_sync(tmp_path):
    mac, v2 = _estate(tmp_path)
    (mac / "other.py").write_text("my edit\n")
    text = _run(mac)
    assert "synced" in text and v2 in text, text
    assert (mac / "other.py").read_text() == "my edit\n"


def test_unpushed_commit_is_blocked_not_rebased(tmp_path):
    mac, _ = _estate(tmp_path)
    _git(mac, "config", "user.email", "t@t"); _git(mac, "config", "user.name", "t")
    (mac / "other.py").write_text("local\n"); _git(mac, "commit", "-qam", "local")
    text = _run(mac)
    assert "BLOCKED" in text and "ahead" in text, text
    assert _git(mac, "rev-list", "--count", "origin/main..HEAD") == "1"


def test_dead_remote_is_blind_never_a_crash(tmp_path):
    mac, _ = _estate(tmp_path)
    _git(mac, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    text = _run(mac)
    assert text.startswith("[sync] BLIND"), text


def test_wired_first_at_session_start_and_hook_run_passes_it():
    import json
    settings = json.loads((HERE / "settings" / "settings.json").read_text())
    starts = [h["command"] for m in settings["hooks"]["SessionStart"] for h in m["hooks"]]
    assert starts and starts[0].endswith("sync-guard.py"), starts[:2]
    mac_env = {**os.environ, "SYNC_GUARD_DIR": str(HERE), "HOOK_OUTCOMES": os.devnull}
    proc = subprocess.run([sys.executable, str(RUN), str(GUARD)], text=True, capture_output=True, input="{}", env=mac_env)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)


def test_detached_submodule_checkout_moves_to_main(tmp_path):
    """The real ~/.claude/scripts is a submodule: detached HEAD is its normal state, not a block."""
    mac, v2 = _estate(tmp_path)
    _git(mac, "checkout", "-q", "--detach", "HEAD")
    text = _run(mac)
    assert "synced" in text and v2 in text, text
    assert _git(mac, "rev-parse", "--short", "HEAD") == v2
    assert _git(mac, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"


def test_local_copy_that_already_equals_main_is_not_a_collision(tmp_path):
    """Measured 2026-08-28: 4 of the 7 'colliding' files on the Mac were byte-identical to main."""
    mac, v2 = _estate(tmp_path)
    (mac / "rule-guard.py").write_text("v2\n")
    text = _run(mac)
    assert "synced" in text and v2 in text, text
    assert _git(mac, "status", "--porcelain") == ""
