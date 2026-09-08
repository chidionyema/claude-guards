import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
import subprocess

import pytest

# Dynamically add the repository root to sys.path to import estate_broadcast
# Assuming this test file is at claude-guards/tests/test_incident_deadletter.py
# and estate_broadcast.py is at claude-guards/estate_broadcast.py
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from estate_broadcast import mirror_to_github, format_row, GH_BOARD_ISSUE, GH_REPO, DEADLETTER as ORIGINAL_DEADLETTER_PATH

@pytest.fixture
def temp_deadletter_file(monkeypatch):
    """Fixture to create a temporary dead-letter file path and patch DEADLETTER."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir) / "board-deadletter.jsonl"
        monkeypatch.setattr("estate_broadcast.DEADLETTER", temp_path)
        yield temp_path

@pytest.fixture
def mock_subprocess_run(monkeypatch):
    """Fixture to mock subprocess.run."""
    with mock.patch("subprocess.run") as mock_run:
        yield mock_run

def test_mirror_to_github_deadletters_on_failure(temp_deadletter_file, mock_subprocess_run, capsys):
    """
    Test that mirror_to_github dead-letters a record when gh issue comment fails.
    """
    # Simulate gh issue comment failure
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, "gh issue comment", stderr="gh error output")

    sample_record = {
        "ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "from": "test-agent",
        "kind": "test",
        "priority": "info",
        "message": "This is a test message for dead-lettering."
    }

    # Call the function under test
    success = mirror_to_github(sample_record)

    # Assert that the call failed
    assert not success

    # Assert that gh issue comment was called with the correct arguments
    expected_body = format_row(sample_record)
    mock_subprocess_run.assert_called_once_with(
        ["gh", "issue", "comment", GH_BOARD_ISSUE, "--repo", GH_REPO, "--body", expected_body],
        check=True, capture_output=True, text=True, timeout=30
    )

    # Assert that the dead-letter file was created and contains the record
    assert temp_deadletter_file.exists()
    with open(temp_deadletter_file, "r") as f:
        deadletter_content = [json.loads(line) for line in f]
    assert len(deadletter_content) == 1
    assert deadletter_content[0]["record"] == sample_record
    assert "error" in deadletter_content[0]
    assert "ts" in deadletter_content[0]

    # Assert that a warning was printed to stderr
    outerr = capsys.readouterr()
    assert "WARN" in outerr.err
    assert "dead-lettered to" in outerr.err
    assert str(temp_deadletter_file) in outerr.err

def test_mirror_to_github_succeeds(temp_deadletter_file, mock_subprocess_run):
    """
    Test that mirror_to_github successfully posts to GitHub and does not dead-letter.
    """
    # Simulate gh issue comment success
    mock_subprocess_run.return_value = mock.Mock(stdout="Comment created", stderr="", returncode=0)

    sample_record = {
        "ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "from": "test-agent",
        "kind": "test",
        "priority": "info",
        "message": "This is a successful test message."
    }

    # Call the function under test
    success = mirror_to_github(sample_record)

    # Assert that the call succeeded
    assert success

    # Assert that gh issue comment was called
    mock_subprocess_run.assert_called_once()

    # Assert that the dead-letter file was NOT created
    assert not temp_deadletter_file.exists()
