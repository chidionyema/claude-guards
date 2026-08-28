"""Incident cg#183, 2026-08-28 00:5xZ: merge-divergence-hook.py refused `git merge origin/main`
on a two-hour-old idp branch (18 commits / 56 files, threshold 50) while the pre-push hook
refuses any branch behind main -- two guards, no path through. And the guard it imports,
merge-target-divergence-guard.py, was never in git (LAW 24). Rule: the default branch of the
remote HEAD pushes to is never a wrong sibling; fork/main at the incident numbers still is."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "merge-target-divergence-guard.py"


def _load():
    spec = importlib.util.spec_from_file_location("divergence_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _incident_git(default_branch: str):
    """git as the guard saw it that night: origin/HEAD -> default_branch, pushes go to origin,
    and the target is 1201 commits / 5011 files from merge-base (the real fork/main numbers)."""

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["git", "symbolic-ref"]:
            return default_branch
        if cmd[:3] == ["git", "config", "--get"] and cmd[3] == "remote.pushDefault":
            return "origin"
        if cmd[:2] == ["git", "merge-base"]:
            return "deadbeef"
        if cmd[:2] == ["git", "diff"]:
            return "5011 files changed, 900000 insertions(+), 1 deletion(-)"
        if cmd[:2] == ["git", "rev-list"]:
            return "1201"
        return ""

    return fake_run


def test_the_guard_is_tracked_in_git() -> None:
    assert GUARD.is_file(), "merge-divergence-hook.py imports a file that is not in the repository"


def test_own_origin_main_is_permitted_at_any_distance() -> None:
    mod = _load()
    with mock.patch.object(mod, "run", side_effect=_incident_git("origin/main")):
        safe, msg = mod.check("origin/main")
    assert safe, msg
    assert "your own remote origin" in msg


def test_fork_main_at_the_incident_numbers_is_still_refused() -> None:
    mod = _load()
    with mock.patch.object(mod, "run", side_effect=_incident_git("origin/main")):
        safe, msg = mod.check("fork/main")
    assert not safe, msg
    assert "1201 commits / 5011 files" in msg


def test_a_worktree_with_no_origin_head_still_recognises_main() -> None:
    mod = _load()

    def no_head(cmd, cwd=None):
        if cmd[:2] == ["git", "symbolic-ref"]:
            return ""
        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            return "abc123"
        return _incident_git("")(cmd, cwd)

    with mock.patch.object(mod, "run", side_effect=no_head):
        safe, msg = mod.check("origin/main")
        assert safe, msg
        safe_peer, msg_peer = mod.check("origin/feat/peer")
    assert not safe_peer, msg_peer
