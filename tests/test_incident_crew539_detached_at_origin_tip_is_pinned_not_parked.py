"""Incident crew#539, 2026-08-28 03:5xZ: com.founder.ingit reported 38 load-bearing holes and most
of them were `checked out on 'HEAD', not 'main'` for ~/dev/code/idp, ~/dev/code/crew and
~/.claude/scripts -- checkouts moved with `git checkout --detach origin/main` on purpose, so a
peer's branch never hides merged rows from the scheduler. Both rules (launchd_drift.parked and
in-git.check_repos) compared the branch name only. Rule: detached exactly at origin/<default> is
pinned; detached one commit past it is still parked."""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path):
    """A clone detached exactly at origin/main, with one commit on main behind it."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    seed = tmp_path / "seed"
    _git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty",
         "-m", "seed", cwd=seed)
    _git("push", "-q", "origin", "HEAD:main", cwd=seed)
    work = tmp_path / "work"
    _git("clone", "-q", str(origin), str(work), cwd=tmp_path)
    _git("checkout", "-q", "--detach", "origin/main", cwd=work)
    return work


def _drift_past_tip(work):
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty",
         "-m", "drift", cwd=work)


def test_launchd_drift_detached_at_tip_is_pinned_then_flagged_once_it_drifts(clone):
    drift = _load("launchd_drift", ROOT / "estate" / "launchd_drift.py")
    script = clone / "job.py"
    script.write_text("print('job')\n")
    assert drift.parked("com.test.job", [str(script)]) == []
    _drift_past_tip(clone)
    hits = drift.parked("com.test.job", [str(script)])
    assert len(hits) == 1 and hits[0][1] == "HEAD" and hits[0][2] == "main"


def test_in_git_check_repos_detached_at_tip_is_pinned_then_flagged_once_it_drifts(clone):
    ingit = _load("in_git", ROOT / "estate" / "in-git.py")
    d = {"repos": [{"path": str(clone), "branch": "main"}]}
    _, holes = ingit.check_repos(d, None)
    assert not [h for h in holes if "checked out on" in h], holes
    _drift_past_tip(clone)
    _, holes = ingit.check_repos(d, None)
    assert [h for h in holes if "checked out on 'HEAD', not 'main'" in h], holes
