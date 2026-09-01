"""Incident 2026-09-01: hook-run's child group must die with the wrapper.

Tests that:
1. When hook-run times out, it kills the entire process group (grandchild included)
2. When hook-run receives SIGTERM, it kills the grandchild process
"""

import os
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK_RUN = os.path.join(HERE, "hook-run.py")


def test_timeout_kills_grandchild():
    """When hook-run times out, the grandchild process must be killed."""
    marker = f"marker-{uuid.uuid4().hex[:8]}"

    # Create a hook that spawns a grandchild sleep process, then sleeps itself
    hook_script = f"""#!/usr/bin/env python3
import subprocess
import sys
import time

# Start a grandchild that will run for 300 seconds
subprocess.Popen(["sh", "-c", "exec sleep 300 # {marker}"])
# Sleep longer than hook-run's timeout
time.sleep(10)
print("hook completed")
"""

    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(hook_script)
        hook_path = f.name

    try:
        # Run hook-run with a 1 second timeout
        result = subprocess.run(
            [sys.executable, HOOK_RUN, hook_path],
            input=b"{}",  # empty stdin
            capture_output=True,
            timeout=10,
            env={**os.environ, "HOOK_TIMEOUT": "1"},
        )

        # Should return exit 2 with refusal JSON
        assert result.returncode == 2, f"Expected exit 2, got {result.returncode}"

        import json

        output = json.loads(result.stdout.decode("utf-8", errors="replace"))
        assert "no verdict inside 1s" in output.get("reason", ""), (
            f"Expected 'no verdict inside 1s' in reason, got {output.get('reason')}"
        )

        # Now check that the grandchild sleep process is gone
        # Wait up to 3 seconds for the process to be killed
        found = True
        for _ in range(6):  # 6 * 0.5 = 3 seconds
            time.sleep(0.5)
            ps_result = subprocess.run(
                ["ps", "-eo", "pid,pgid,command"], capture_output=True, text=True
            )
            if marker not in ps_result.stdout:
                found = False
                break

        assert not found, (
            f"Grandchild process with marker {marker} should be killed but still running"
        )
    finally:
        os.unlink(hook_path)


def test_signal_kills_grandchild():
    """When hook-run receives SIGTERM, it must kill the grandchild process."""
    marker = f"marker-signal-{uuid.uuid4().hex[:8]}"

    hook_script = f"""#!/usr/bin/env python3
import subprocess
import sys
import time

# Start a grandchild that will run for 300 seconds
subprocess.Popen(["sh", "-c", "exec sleep 300 # {marker}"])
# Sleep longer than our test delay
time.sleep(10)
print("hook completed")
"""

    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(hook_script)
        hook_path = f.name

    try:
        # Start hook-run in background
        # Use DEVNULL instead of PIPE for stdin - PIPE can interfere with signal handling
        proc = subprocess.Popen(
            [sys.executable, HOOK_RUN, hook_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "HOOK_TIMEOUT": "10"},
        )

        # Wait 1 second to ensure hook-run has started
        time.sleep(1.0)
        proc.send_signal(subprocess.signal.SIGTERM)

        # Wait for process to exit
        proc.wait(timeout=5)

        # Should return exit 2
        assert proc.returncode == 2, f"Expected exit 2, got {proc.returncode}"

        # Now check that the grandchild sleep process is gone within 3 seconds
        found = True
        for _ in range(6):  # 6 * 0.5 = 3 seconds
            time.sleep(0.5)
            ps_result = subprocess.run(
                ["ps", "-eo", "pid,pgid,command"], capture_output=True, text=True
            )
            if marker not in ps_result.stdout:
                found = False
                break

        assert not found, (
            f"Grandchild process with marker {marker} should be killed but still running"
        )
    finally:
        os.unlink(hook_path)
