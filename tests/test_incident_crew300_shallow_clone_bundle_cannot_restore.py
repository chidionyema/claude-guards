"""Incident test: crew#300 round 9 (idp run 33100565959): one of 47 R2 bundles could not be cloned back.

The source was a depth-1 clone (Documents/code/hermes-v2.ARCHIVED.20260822/hermes-agent-self-evolution).
`git bundle create --all` from a shallow clone writes a file that `git bundle verify` calls a
complete history and `git clone` refuses with "remote did not send all necessary objects".
estate_bundle_push.sh now skips a shallow repo before it counts its commits, and removes the
latest.bundle it left behind. Proved both ways here with real git, no network.
"""
import os
import re
import subprocess

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUSHER = os.path.join(HERE, "estate", "estate_bundle_push.sh")


def git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, timeout=60)


def _origin(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    git("init", "-q", "-b", "main", cwd=src)
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "one", cwd=src)
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "two", cwd=src)
    return src


def _bundle_clones(repo, tmp_path, tag):
    b = tmp_path / f"{tag}.bundle"
    assert git("bundle", "create", str(b), "--all", cwd=repo).returncode == 0
    assert git("bundle", "verify", str(b), cwd=repo).returncode == 0, "verify is the lie: it passes for both"
    r = git("clone", "-q", "--bare", str(b), str(tmp_path / f"{tag}.git"))
    return r.returncode == 0, r.stderr


def test_a_shallow_clone_bundle_verifies_but_cannot_be_cloned(tmp_path):
    src = _origin(tmp_path)
    shallow = tmp_path / "shallow"
    assert git("clone", "-q", "--depth", "1", f"file://{src}", str(shallow)).returncode == 0
    assert git("rev-parse", "--is-shallow-repository", cwd=shallow).stdout.strip() == "true"
    ok, err = _bundle_clones(shallow, tmp_path, "shallow")
    assert not ok and "did not send all necessary objects" in err, err


def test_a_full_clone_bundle_clones_back(tmp_path):
    src = _origin(tmp_path)
    full = tmp_path / "full"
    assert git("clone", "-q", f"file://{src}", str(full)).returncode == 0
    ok, err = _bundle_clones(full, tmp_path, "full")
    assert ok, err


def test_the_pusher_skips_a_shallow_repo_before_counting_its_commits():
    s = open(PUSHER).read()
    guard = s.find('rev-parse --is-shallow-repository')
    count = s.find('n=$(gplan "$d" rev-list --count --all --not --remotes')
    assert 0 < guard < count, "the shallow check must run before any commit count plans a bundle"
    block = s[guard:count]
    assert "continue" in block and "rclone deletefile" in block and "latest.bundle" in block
    assert re.search(r'^\s*#:.*33100565959', s, re.M), "the measurement that found it is named"
    assert subprocess.run(["bash", "-n", PUSHER], capture_output=True).returncode == 0
