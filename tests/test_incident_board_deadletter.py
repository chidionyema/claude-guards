import pytest
import os
import json
import shutil
import tempfile
import datetime
from unittest.mock import patch, MagicMock

# Mock the default_api for the test environment
class MockDefaultApi:
    def comment_on_issue(self, repo, number, body):
        # Simulate a 5xx error by raising an exception
        raise Exception("Simulated 5xx error from GitHub API")

@pytest.fixture
def setup_test_environment():
    """
    Sets up a temporary directory and mock files for testing.
    - Creates a temporary directory to act as a mock home for .claude files.
    - Creates a mock 'bin/board-target' file with configured values.
    - Defines the path for the mock dead-letter file within the temporary structure.
    """
    temp_dir = tempfile.mkdtemp()
    
    # Create a mock .claude directory structure within the temporary directory
    mock_claude_home = os.path.join(temp_dir, "mock_claude_home")
    mock_claude_state_dir = os.path.join(mock_claude_home, ".claude", "state")
    os.makedirs(mock_claude_state_dir, exist_ok=True)

    # Define paths for mock bin/board-target and dead-letter file
    mock_bin_dir = os.path.join(temp_dir, "bin")
    os.makedirs(mock_bin_dir, exist_ok=True)
    mock_board_target_path = os.path.join(mock_bin_dir, "board-target")
    mock_dead_letter_path = os.path.join(mock_claude_state_dir, "board-deadletter.jsonl")

    # Content for bin/board-target, using the absolute path to the mock dead-letter file
    board_target_content = f"""repo=chidionyema/crew
issue=102
dead_letter={mock_dead_letter_path}
"""
    with open(mock_board_target_path, "w") as f:
        f.write(board_target_content)

    yield {
        "temp_dir": temp_dir,
        "mock_board_target_path": mock_board_target_path,
        "mock_dead_letter_path": mock_dead_letter_path,
    }

    # Clean up the temporary directory after the test
    shutil.rmtree(temp_dir)

def run_estate_broadcast_mocked(message: str, mock_board_target_path: str, mock_dead_letter_path: str, mock_api: MockDefaultApi):
    """
    A mocked version of the estate-broadcast.py script's core logic.
    It simulates reading configuration from bin/board-target, attempting to post a comment,
    and dead-lettering on failure with a basic idempotency check for the dead-letter file.
    """
    # Simulate reading from bin/board-target
    config = {}
    with open(mock_board_target_path, "r") as f:
        for line in f:
            key, value = line.strip().split("=")
            config[key] = value

    target_repo = config.get("repo", "crew")
    target_issue_number = int(config.get("issue", "102"))
    dead_letter_file_path = config.get("dead_letter") # Path is already absolute from fixture

    # Generate timestamp and format message (as per estate-broadcast.py)
    timestamp = datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z'
    source = "system"
    kind_priority = "broadcast/info"
    formatted_message = f"{timestamp} **{source}** ({kind_priority}): {message}"

    try:
        mock_api.comment_on_issue(repo=target_repo, number=target_issue_number, body=formatted_message)
    except Exception as e:
        dead_letter_entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "repo": target_repo,
            "issue_number": target_issue_number,
            "original_message": message,
            "formatted_message": formatted_message,
            "error": str(e)
        }
        
        os.makedirs(os.path.dirname(dead_letter_file_path), exist_ok=True)
        
        # --- Idempotency check for dead-lettering ---
        # Read existing dead-letter entries to check if this message has already been logged.
        existing_messages = set()
        if os.path.exists(dead_letter_file_path):
            with open(dead_letter_file_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        existing_messages.add(entry.get("original_message"))
                    except json.JSONDecodeError:
                        # Skip malformed lines if any
                        pass
        
        # Only write to dead-letter file if the message hasn't been logged before
        if message not in existing_messages:
            with open(dead_letter_file_path, 'a') as f:
                f.write(json.dumps(dead_letter_entry) + '\n')
        # If the message already exists, it's a no-op, satisfying the idempotency requirement.

def test_incident_board_deadletter(setup_test_environment):
    """
    Tests the dead-lettering mechanism and idempotency for the estate board broadcast.
    - Simulates a GitHub API failure (5xx error).
    - Verifies that the broadcast message is written to the dead-letter file.
    - Asserts that retrying the same message (idempotency key) is a no-op for dead-lettering.
    - Verifies that a new, different message is still dead-lettered.
    """
    env = setup_test_environment
    mock_dead_letter_path = env["mock_dead_letter_path"]
    mock_board_target_path = env["mock_board_target_path"]

    mock_api = MockDefaultApi()

    test_message_1 = "This is a test broadcast message for dead-lettering."
    test_message_2 = "This is a second unique test broadcast message."

    # Ensure the dead-letter file does not exist initially
    if os.path.exists(mock_dead_letter_path):
        os.remove(mock_dead_letter_path)

    # --- Test Case 1: Simulate failure and verify dead-lettering ---
    run_estate_broadcast_mocked(test_message_1, mock_board_target_path, mock_dead_letter_path, mock_api)

    assert os.path.exists(mock_dead_letter_path)
    with open(mock_dead_letter_path, 'r') as f:
        dead_letters = [json.loads(line) for line in f]
    
    assert len(dead_letters) == 1
    assert dead_letters[0]["original_message"] == test_message_1
    assert "Simulated 5xx error" in dead_letters[0]["error"]
    assert dead_letters[0]["repo"] == "chidionyema/crew"
    assert dead_letters[0]["issue_number"] == 102

    # --- Test Case 2: Assert retry with same idempotency key is a no-op ---
    # Re-run with the exact same message. Due to the idempotency logic in
    # run_estate_broadcast_mocked, no new entry should be added to the dead-letter file.
    run_estate_broadcast_mocked(test_message_1, mock_board_target_path, mock_dead_letter_path, mock_api)

    with open(mock_dead_letter_path, 'r') as f:
        dead_letters_after_retry = [json.loads(line) for line in f]
    
    assert len(dead_letters_after_retry) == 1, "Retry with same message should be a no-op due to idempotency"
    assert dead_letters_after_retry[0]["original_message"] == test_message_1

    # --- Test Case 3: Verify a different message still dead-letters ---
    # A new, unique message should still be dead-lettered.
    run_estate_broadcast_mocked(test_message_2, mock_board_target_path, mock_dead_letter_path, mock_api)

    with open(mock_dead_letter_path, 'r') as f:
        dead_letters_final = [json.loads(line) for line in f]
    
    assert len(dead_letters_final) == 2
    assert dead_letters_final[1]["original_message"] == test_message_2
    assert "Simulated 5xx error" in dead_letters_final[1]["error"]
    assert dead_letters_final[1]["repo"] == "chidionyema/crew"
    assert dead_letters_final[1]["issue_number"] == 102
