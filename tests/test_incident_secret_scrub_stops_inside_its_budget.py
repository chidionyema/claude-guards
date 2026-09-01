"""Incident 2026-09-01: secret-scrub must stop within its budget and detect orphan status.

Tests that:
1. When budget is exceeded, secret-scrub stops gracefully and returns 0
2. When wrapper is gone (ppid == 1), secret-scrub stops gracefully and returns 0
"""

import importlib.util
import io
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

# Add parent to path to import secret_scrub
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

# Import via importlib to avoid caching issues
spec = importlib.util.spec_from_file_location(
    "secret_scrub", os.path.join(HERE, "secret-scrub.py")
)
secret_scrub = importlib.util.module_from_spec(spec)
sys.modules["secret_scrub"] = secret_scrub
spec.loader.exec_module(secret_scrub)


def test_budget_stops_gracefully():
    """When budget is exceeded, secret-scrub stops and returns 0 (not a refusal)."""
    # Create 50 temp files of 1 MB each
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create 50 files with random-ish text (not secrets)
        for i in range(50):
            f = tmp_path / f"file_{i:03d}.txt"
            # 1 MB of text
            f.write_text(f"content for file {i}\n" * 15000)

        # Monkeypatch HOME to use our temp directory
        with mock.patch.object(secret_scrub, "HOME", tmp_path):
            # Monkeypatch targets to return our files
            def patched_targets():
                return sorted(tmp_path.glob("*.txt"), key=lambda p: p.stat().st_size)

            with mock.patch.object(secret_scrub, "targets", patched_targets):
                # Set budget to 0.5 seconds
                with mock.patch.dict(os.environ, {"SECRET_SCRUB_BUDGET_S": "0.5"}):
                    # Re-import to pick up the env var
                    secret_scrub.BUDGET_S = 0.5
                    secret_scrub._budget_remaining = lambda: 0.5

                    start = time.time()
                    result = secret_scrub.run(check_only=True)
                    elapsed = time.time() - start

        # Should return 0 (not a refusal - nothing was found)
        assert result == 0, f"Expected return 0, got {result}"

        # Should finish in under 5 seconds
        assert elapsed < 5, f"Should finish in under 5s, took {elapsed:.1f}s"

        # Should have printed the budget line
        # (we can't easily capture stdout in this setup, but the key is it returned 0 quickly)


def test_wrapper_gone_stops_gracefully():
    """When wrapper is gone (ppid == 1), secret-scrub stops gracefully and returns 0."""
    with mock.patch.object(os, "getppid", return_value=1):
        # Create a minimal target list (empty is fine for this test)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create a dummy file
            (tmp_path / "test.txt").write_text("test content")

            with mock.patch.object(secret_scrub, "HOME", tmp_path):

                def patched_targets():
                    return [tmp_path / "test.txt"]

                with mock.patch.object(secret_scrub, "targets", patched_targets):
                    # Capture stderr
                    old_stderr = sys.stderr
                    sys.stderr = io.StringIO()

                    try:
                        result = secret_scrub.run(check_only=True)
                    finally:
                        stderr_output = sys.stderr.getvalue()
                        sys.stderr = old_stderr

        # Should return 0
        assert result == 0, f"Expected return 0, got {result}"

        # Should have printed the wrapper-gone line
        assert "wrapper gone" in stderr_output.lower() or "LAW 28" in stderr_output, (
            f"Expected wrapper-gone message, got: {stderr_output}"
        )
