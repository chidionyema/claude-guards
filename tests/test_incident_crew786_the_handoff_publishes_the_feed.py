"""crew#786: the handoff publishes the feed.

A handoff append triggers publishing a redacted 48-hour feed and an hourly
NEXT.md to the IDP state branch.
"""

import datetime as dt
import importlib.util
import os
import shutil
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent


def _feed_guard():
    spec = importlib.util.spec_from_file_location("feed_guard", HERE / "feed-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_public_47h_kept_49h_dropped():
    """render_public keeps entries within 48h window, drops older ones, keeps header."""
    fg = _feed_guard()
    t_now = fg.now()
    t_47h = t_now - dt.timedelta(hours=47)
    t_49h = t_now - dt.timedelta(hours=49)

    feed_text = (
        """# Estate feed

One handoff per session per 15 minutes.

## 2024-01-01T00:00Z · session old · lane old-lane
🔴 old
📍 old

## """
        + t_47h.strftime("%Y-%m-%dT%H:%MZ")
        + """ · session recent · lane recent-lane
🔴 recent
📍 recent

## """
        + t_49h.strftime("%Y-%m-%dT%H:%MZ")
        + """ · session old49 · lane old-lane
🔴 old49
📍 old49
"""
    )

    rendered = fg.render_public(feed_text, t_now)

    # 47h entry should be kept
    assert "recent" in rendered
    # 49h entry should be dropped
    assert "old49" not in rendered
    # Header should be kept
    assert "Estate feed" in rendered


def test_redact_github_token():
    """redact replaces a GitHub token with [REDACTED]."""
    fg = _feed_guard()
    gitleaks = shutil.which("gitleaks")
    if not gitleaks:
        pytest.skip("gitleaks not installed")

    test_text = "My token is " + "ghp_" + "abcdefgh" * 4 + " and it's secret"
    redacted = fg.redact(test_text)

    assert "[REDACTED]" in redacted
    # The actual token should not appear in redacted text
    assert "ghp_" not in redacted


def test_publish_to_local_bare_repo():
    """publish() works against a local bare repo with state/live-diagram branch."""
    fg = _feed_guard()
    os.environ["FEED_GUARD_NO_PUBLISH"] = "1"

    with tempfile.TemporaryDirectory() as td:
        # Create a bare repo
        bare_dir = Path(td) / "bare.git"
        bare_dir.mkdir()
        subprocess_run(["git", "init", "--bare", str(bare_dir)], check=True, cwd=td)

        # Create a working clone to set up the branch
        setup_dir = Path(td) / "setup"
        subprocess_run(
            ["git", "clone", str(bare_dir), str(setup_dir)], check=True, cwd=td
        )

        # Create initial commit on the branch
        (setup_dir / "docs").mkdir(parents=True)
        (setup_dir / "docs" / "FEED.md").write_text("initial\n")
        subprocess_run(
            ["git", "checkout", "-b", "state/live-diagram"], check=True, cwd=setup_dir
        )
        subprocess_run(["git", "add", "."], check=True, cwd=setup_dir)
        subprocess_run(
            [
                "git",
                "-c",
                "user.name=feed-test",
                "-c",
                "user.email=feed-test@example.invalid",
                "commit",
                "-m",
                "initial",
            ],
            check=True,
            cwd=setup_dir,
        )
        subprocess_run(
            ["git", "push", "origin", "state/live-diagram"], check=True, cwd=setup_dir
        )

        # Create feed for publishing - use a timestamp within the last 48 hours
        import datetime

        t_now = fg.now()
        t_recent = t_now - datetime.timedelta(hours=1)  # 1 hour ago
        feed_dir = Path(td) / "feed"
        feed_dir.mkdir()
        feed = feed_dir / "feed.md"
        feed.write_text(
            f"# Estate feed\n\n## {t_recent.strftime('%Y-%m-%dT%H:%MZ')} · session test · lane test-lane\n🔴 test\n📍 test\n"
        )

        # Monkeypatch PUBLISH_CLONE on the publish library (crew#786: it is feed_publish.py now)
        import sys as _sys

        fp = _sys.modules["feed_publish"]
        # This test grades the git plumbing, not the scanner: CI runners carry no
        # gitleaks, and redaction has its own tests above. Publish nothing changes.
        original_redact = fp.redact
        fp.redact = lambda text: text
        publish_clone = Path(td) / "publish"
        original_publish_clone = fp.PUBLISH_CLONE

        # Create publish clone manually
        subprocess_run(
            [
                "git",
                "clone",
                str(bare_dir),
                str(publish_clone),
                "--branch",
                "state/live-diagram",
                "--single-branch",
            ],
            check=True,
            cwd=td,
        )

        # Patch the library's PUBLISH_CLONE
        fp.PUBLISH_CLONE = publish_clone
        fp.STATE_BRANCH = "state/live-diagram"

        try:
            t = fg.now()
            receipt = fg.publish(feed, t)

            # First publish should succeed
            assert receipt.startswith("ok    feed-publish:")
            assert "unchanged" not in receipt

            # The bare repo should now have the feed
            verify_dir = Path(td) / "verify"
            subprocess_run(
                [
                    "git",
                    "clone",
                    str(bare_dir),
                    str(verify_dir),
                    "--branch",
                    "state/live-diagram",
                    "--single-branch",
                ],
                check=True,
                cwd=td,
            )
            assert (verify_dir / "docs" / "FEED.md").exists()
            content = (verify_dir / "docs" / "FEED.md").read_text()
            assert "test" in content

            # Second publish with same feed should return unchanged
            receipt2 = fg.publish(feed, t)
            assert "unchanged" in receipt2

            # Move the branch (commit from another clone)
            other_dir = Path(td) / "other"
            subprocess_run(
                [
                    "git",
                    "clone",
                    str(bare_dir),
                    str(other_dir),
                    "--branch",
                    "state/live-diagram",
                    "--single-branch",
                ],
                check=True,
                cwd=td,
            )
            (other_dir / "docs" / "OTHER.md").write_text("other\n")
            subprocess_run(["git", "add", "."], check=True, cwd=other_dir)
            subprocess_run(
                [
                    "git",
                    "-c",
                    "user.name=feed-test",
                    "-c",
                    "user.email=feed-test@example.invalid",
                    "commit",
                    "-m",
                    "other",
                ],
                check=True,
                cwd=other_dir,
            )
            subprocess_run(
                ["git", "push", "origin", "state/live-diagram"],
                check=True,
                cwd=other_dir,
            )

            # Publish again - should handle the rebase
            receipt3 = fg.publish(feed, t)
            assert receipt3.startswith("ok    feed-publish:")
        finally:
            fp.PUBLISH_CLONE = original_publish_clone
            fp.redact = original_redact


def subprocess_run(args, check=True, cwd=None):
    import subprocess

    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {args}\n{result.stderr}")
    return result


def test_redact_publishes_nothing_when_the_scanner_errors(tmp_path, monkeypatch):
    """A scanner that exits non-zero or writes no report means: publish nothing (None),
    never the unredacted text (review of the first cut, 2026-09-01)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fg", str(Path(__file__).resolve().parent.parent / "feed-guard.py")
    )
    fg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fg)
    fake = tmp_path / "gitleaks"
    fake.write_text("#!/bin/sh\nexit 3\n")
    fake.chmod(0o755)
    monkeypatch.setattr(fg.shutil, "which", lambda name: str(fake))
    assert fg.redact("token " + "ghp_" + "abcd" * 9 + "") is None
