import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
import pytest

# Define paths relative to the test file for consistent access
TEST_DIR = Path(__file__).parent
REPO_ROOT = TEST_DIR.parent

# Mock gh command for testing dead-letter functionality
class MockGh: # noqa: E742
    def __init__(self, fail_mirror=False):
        self.fail_mirror = fail_mirror
        self.calls = []

    def run(self, cmd, check, capture_output, text, timeout):
        self.calls.append(cmd)
        if self.fail_mirror:
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="Mocked gh failure")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

@pytest.fixture
def mock_gh(monkeypatch):
    mock = MockGh()
    monkeypatch.setattr(subprocess, "run", mock.run)
    return mock

@pytest.fixture
def mock_gh_fail(monkeypatch):
    mock = MockGh(fail_mirror=True)
    monkeypatch.setattr(subprocess, "run", mock.run)
    return mock

@pytest.fixture
def setup_broadcast_env(tmp_path, monkeypatch):
    # Create a temporary home directory for .claude files
    mock_home = tmp_path / "mock_home"
    mock_home.mkdir()
    monkeypatch.setenv("HOME", str(mock_home))

    # Create mock bin directory and board-target file
    mock_bin = mock_home / ".claude" / "bin"
    mock_bin.mkdir(parents=True)
    board_target_path = mock_bin / "board-target"
    board_target_path.write_text(
        "repo=chidionyema/crew\nissue=102\ndead_letter=" + str(mock_home / ".claude" / "state" / "board-deadletter.jsonl") + "\n"
    )

    # Create mock .claude directory for board and lock files
    (mock_home / ".claude").mkdir(exist_ok=True)
    (mock_home / ".claude" / "state").mkdir(exist_ok=True)

    # Ensure estate-broadcast.py can be imported
    monkeypatch.syspath_insert(0, REPO_ROOT)
    return mock_home

def test_dead_letter_on_github_mirror_failure(mock_gh_fail, setup_broadcast_env):
    mock_home = setup_broadcast_env
    deadletter_path = mock_home / ".claude" / "state" / "board-deadletter.jsonl"

    # Simulate a broadcast
    from estate_broadcast import append_broadcast, mirror_to_github

    record = {
        "ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "from": "test-session",
        "kind": "test",
        "message": "This is a test message for dead-lettering.",
        "priority": "high"
    }

    # Append to local board (should succeed)
    append_broadcast(record)

    # Mirror to GitHub (should fail and dead-letter)
    assert not mirror_to_github(record)

    # Verify dead-letter file exists and contains the record
    assert deadletter_path.exists()
    with open(deadletter_path, "r") as f:
        dead_letter_content = f.read()
        dead_letter_record = json.loads(dead_letter_content)
        assert dead_letter_record["record"]["message"] == record["message"]
        assert "Mocked gh failure" in dead_letter_record["error"]

def test_idempotency_key_added(setup_broadcast_env):
    mock_home = setup_broadcast_env
    from estate_broadcast import append_broadcast, read_board_validated

    record = {
        "from": "test-session",
        "kind": "test",
        "message": "Test message for idempotency key."
    }

    append_broadcast(record)
    records = read_board_validated()
    assert len(records) == 1
    assert "idempotency_key" in records[0]
    assert isinstance(records[0]["idempotency_key"], str)

def test_no_duplicate_on_retry_with_idempotency_key(mock_gh_fail, setup_broadcast_env):
    mock_home = setup_broadcast_env
    deadletter_path = mock_home / ".claude" / "state" / "board-deadletter.jsonl"

    from estate_broadcast import append_broadcast, mirror_to_github, read_board_validated

    record = {
        "from": "test-session",
        "kind": "test",
        "message": "Test message for idempotency key and retry."
    }

    # First attempt: append to local board, mirror fails, dead-lettered
    append_broadcast(record)
    assert not mirror_to_github(record)

    # Get the idempotency key from the first record
    first_record = read_board_validated()[0]
    idempotency_key = first_record["idempotency_key"]

    # Second attempt with the same idempotency key: should not append a duplicate locally
    record_with_key = record.copy()
    record_with_key["idempotency_key"] = idempotency_key
    append_broadcast(record_with_key)

    # Verify only one record exists in the local board
    records_after_retry = read_board_validated()
    assert len(records_after_retry) == 1
    assert records_after_retry[0]["idempotency_key"] == idempotency_key

    # Verify only one entry in dead-letter file (from the first mirror attempt)
    with open(deadletter_path, "r") as f:
        dead_letter_entries = f.readlines()
    assert len(dead_letter_entries) == 1
