"""Incident 2026-08-29 03:2xZ: com.estate.restic-backup had failed every night since
2026-08-26 and its Dagster breaker was open, while the R2 repository held a snapshot
1h03m old -- the backup was landing the whole time. restic exits 3 when it wrote the
snapshot but could not read a source, and macOS refuses the xattrs on the Notes
container to a process without Full Disk Access, so 3 is this job's ordinary exit.
Under `set -e` that 3 aborted the script at the backup line, before the age assertion
the script's own comment calls the receipt. Rule: this backup is graded by the age of
the snapshot in the repository, never by restic's exit code -- except a fatal restic
error (1, 2, 10+), which is still a failure."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "estate" / "restic-backup.sh"

FAKE_RESTIC = """#!/bin/sh
echo "$1" >> "$CALLS"
case "$1" in
  backup)    exit $BACKUP_RC ;;
  forget)    exit 0 ;;
  snapshots) printf '[{"short_id":"deadbeef","time":"%s"}]\\n' "$SNAP_TIME" ;;
  *)         exit 99 ;;
esac
"""


def _estate(tmp_path: Path, backup_rc: int, snap_age_hours: float) -> tuple[dict, Path]:
    """A HOME the script can run against: a fake restic, and a restic-env.sh that names
    no secret and reaches no host (the real one sources ~/.config/estate/estate.env)."""
    import datetime

    home = tmp_path / "home"
    (home / ".claude" / "scripts" / "estate").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    (bin_dir / "restic").write_text(FAKE_RESTIC)
    (bin_dir / "restic").chmod(0o755)

    env_sh = home / ".claude" / "scripts" / "estate" / "restic-env.sh"
    env_sh.write_text(f'export PATH="{bin_dir}:$PATH"\n')

    target = home / ".claude" / "scripts" / "estate" / "restic-backup.sh"
    target.write_text(SCRIPT.read_text())
    target.chmod(0o755)

    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=snap_age_hours)
    calls = tmp_path / "calls"
    # A named environment, not the developer's: inheriting os.environ made each of these
    # runs 13s instead of 1s, and a backup script's behaviour must not depend on what the
    # shell that started it happened to export.
    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "BACKUP_RC": str(backup_rc),
        "SNAP_TIME": when.isoformat(),
        "CALLS": str(calls),
    }
    return env, calls


def _run(tmp_path: Path, backup_rc: int, snap_age_hours: float = 1.0):
    env, calls = _estate(tmp_path, backup_rc, snap_age_hours)
    script = Path(env["HOME"]) / ".claude" / "scripts" / "estate" / "restic-backup.sh"
    proc = subprocess.run(["/bin/sh", str(script)], env=env, capture_output=True, text=True)
    return proc, (calls.read_text().split() if calls.exists() else [])


def test_the_incident_exit_3_with_a_fresh_snapshot_is_a_green_backup(tmp_path: Path) -> None:
    proc, calls = _run(tmp_path, backup_rc=3)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr[-400:]}"
    assert "latest snapshot deadbeef" in proc.stdout


def test_exit_3_does_not_stop_the_script_reaching_forget_and_the_age_check(tmp_path: Path) -> None:
    """The bug was where it stopped, not what it returned: prove both later restic calls ran."""
    _, calls = _run(tmp_path, backup_rc=3)
    assert calls == ["backup", "forget", "snapshots"], calls


@pytest.mark.parametrize("rc", [1, 2, 10, 12])
def test_a_fatal_restic_error_is_still_a_failure(tmp_path: Path, rc: int) -> None:
    proc, calls = _run(tmp_path, backup_rc=rc)
    assert proc.returncode == rc, f"restic exit {rc} was swallowed"
    assert calls == ["backup"], f"the script kept going after a fatal restic error: {calls}"


def test_a_stale_snapshot_still_fails_even_when_restic_said_nothing_was_wrong(tmp_path: Path) -> None:
    """The age assertion is the grade, so it has to keep biting on a clean exit."""
    proc, _ = _run(tmp_path, backup_rc=0, snap_age_hours=40)
    assert proc.returncode != 0, "a 40h-old snapshot passed as a backup"
    assert "latest snapshot is" in proc.stderr
