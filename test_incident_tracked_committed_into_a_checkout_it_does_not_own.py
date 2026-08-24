"""tracked.py --sync mirrored load-bearing files into ~/.claude/scripts itself.

That is the checkout every session edits and 33 launchd jobs execute. Whenever a
session had it on a branch, the mirror was committed onto that session's branch,
and the push was then skipped on purpose because pushing another session's branch
collides with its owner. The board records five runs on 2026-08-24 -- 15:53,
17:54, 18:24, 18:54 and 19:43 -- that committed 32, 1, 1, 3 and 34 files and
pushed none of them. The guard that enforces "everything is in git" put nothing
in git for four hours and reported each run as normal operation.

The rule, which is what this test asserts and not the code that implements it:
a scheduled job commits in a checkout it owns, and its work reaches origin/main
whatever branch any session happens to be standing on.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess

import pytest

HERE_DIR = os.path.dirname(os.path.abspath(__file__))


def load():
    ld = importlib.machinery.SourceFileLoader("tracked", os.path.join(HERE_DIR, "tracked.py"))
    spec = importlib.util.spec_from_loader("tracked", ld)
    mod = importlib.util.module_from_spec(spec)
    ld.exec_module(mod)
    return mod


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


@pytest.fixture
def estate(tmp_path):
    """An origin, a shared checkout standing on somebody's branch, and a live file."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "--bare", "--initial-branch=main", ".")

    shared = tmp_path / "shared"
    git(tmp_path, "clone", str(origin), str(shared))
    git(shared, "config", "user.email", "t@t"); git(shared, "config", "user.name", "t")
    (shared / "mirrors").mkdir()
    (shared / "mirrors" / "thing.conf").write_text("old\n")
    git(shared, "add", "-A"); git(shared, "commit", "-m", "seed")
    git(shared, "push", "origin", "main")

    # A session is working here, on its own branch, exactly as on 2026-08-24.
    git(shared, "checkout", "-b", "fix/somebody-elses-work")

    live = tmp_path / "live"
    live.mkdir()
    (live / "thing.conf").write_text("new, and this must reach origin\n")

    (shared / "tracked.json").write_text(json.dumps(
        [{"live": str(live / "thing.conf"), "repo": "mirrors/thing.conf",
          "why": "the incident"}]))
    return tmp_path, origin, shared, live


def run_sync(mod, tmp_path, shared):
    mod.HERE = str(shared)
    mod.MANIFEST = str(shared / "tracked.json")
    mod.HOME = str(tmp_path)
    mod.REPO_ROOT = str(shared)
    mod.WORKTREE = str(tmp_path / "cache" / "tracked-worktree")
    mod.BOARD = str(tmp_path / "board.jsonl")
    return mod.sync()


def test_incident_tracked_committed_into_a_checkout_it_does_not_own(estate):
    """MUST FIRE: the mirror reaches origin/main and the session's branch is untouched."""
    tmp_path, origin, shared, _live = estate
    mod = load()

    head_before = git(shared, "rev-parse", "HEAD")
    assert run_sync(mod, tmp_path, shared) == 0

    # The session's checkout is exactly where it was left.
    assert git(shared, "rev-parse", "--abbrev-ref", "HEAD") == "fix/somebody-elses-work"
    assert git(shared, "rev-parse", "HEAD") == head_before, \
        "the job committed into a checkout it does not own"
    assert git(shared, "status", "--porcelain", "--", "mirrors") == "", \
        "the job left the session's working tree dirty"

    # And the drift is on origin/main, which is the whole point of LAW 24.
    assert git(origin, "show", "main:mirrors/thing.conf") == "new, and this must reach origin"


def test_the_job_does_not_stop_when_it_cannot_have_its_own_checkout(estate):
    """MUST NOT FIRE: an unusable worktree path falls back, it does not raise.

    A mirror taken in an awkward place is recoverable. A mirror not taken at all
    is the thing LAW 24 was written about, so this path must degrade, not stop.
    """
    tmp_path, _origin, shared, _live = estate
    mod = load()
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")

    mod.WORKTREE = str(blocked / "tracked-worktree")
    path, why = (lambda: (setattr(mod, "HERE", str(shared)),
                          setattr(mod, "HOME", str(tmp_path)),
                          mod.own_checkout())[-1])()
    assert path is None, "a worktree cannot live under a regular file"
    assert why, "a refusal with no reason is a refusal nobody can act on"


def test_the_checkout_it_owns_has_no_branch_to_stand_on(estate):
    """MUST NOT FIRE: no session can be standing on the job's HEAD, by construction."""
    tmp_path, _origin, shared, _live = estate
    mod = load()
    mod.HERE = str(shared)
    mod.HOME = str(tmp_path)
    mod.WORKTREE = str(tmp_path / "cache" / "tracked-worktree")

    path, why = mod.own_checkout()
    assert path and not why, why
    assert os.path.realpath(path) != os.path.realpath(str(shared))
    assert subprocess.run(["git", "-C", path, "symbolic-ref", "-q", "HEAD"],
                          capture_output=True).returncode != 0, \
        "the job's checkout is on a branch, so a session can be standing on it"
    assert git(path, "rev-parse", "HEAD") == git(shared, "rev-parse", "origin/main")
