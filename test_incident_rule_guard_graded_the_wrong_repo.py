"""rule-guard refused a 1-file crew PR as "65 files" by grading the session's repo.

2026-08-24: a command assembled a crew worktree entirely through `git -C <path>` (no
leading cd), then ran `gh pr create --repo chidionyema/crew --head feat/delivery-row`.
`_repo_for` only reads a leading `cd`, so it fell back to the session cwd — the
scripts repo, whose branch really was 65 files adrift — and `rule_pr_size` blocked a
one-file PR with another repo's numbers. Third variant of the wrong-repo class the
guard's own comments already record twice.

The rule, in two halves: a `git -C <path>` in the command names the tree the command
runs in just as loudly as a leading cd; and a PR whose `--head` branch is not the
graded checkout's branch is a diff the guard cannot see, so it abstains rather than
accuses. Rung 4, incident test, named for the bug.
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load():
    loader = importlib.machinery.SourceFileLoader(
        "rule_guard", os.path.join(HERE, "rule-guard.py"))
    spec = importlib.util.spec_from_loader("rule_guard", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _mk_repo(root, n_files_on_branch):
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "seed.txt").write_text("seed\n")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-q", "-m", "seed")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-q", "-b", "big-branch")
    for i in range(n_files_on_branch):
        (root / f"f{i}.txt").write_text("x\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "big")
    return root


def test_a_git_dash_c_path_names_the_repo_the_command_runs_in(tmp_path):
    mod = _load()
    target = _mk_repo(tmp_path / "target", 1)
    cmd = 'W=%s\ngit -C "$W" push -q origin big-branch' % target
    assert mod._repo_for(cmd, session_cwd=None) == str(target)


def test_a_pr_whose_head_is_not_this_checkouts_branch_is_not_graded(tmp_path):
    mod = _load()
    wrong = _mk_repo(tmp_path / "wrong", 45)   # over the 40-file ceiling
    mod._ACTIVE_REPO = str(wrong)
    verdict = mod.rule_pr_size(
        "gh pr create --repo o/other --head feat/delivery-row --title t --body b")
    assert verdict is None, verdict


def test_an_oversize_pr_from_its_own_checkout_is_still_blocked(tmp_path):
    mod = _load()
    repo = _mk_repo(tmp_path / "repo", 45)
    mod._ACTIVE_REPO = str(repo)
    verdict = mod.rule_pr_size(
        "gh pr create --head big-branch --title small-fix --body b")
    assert verdict is not None and "45 files" in verdict


if __name__ == "__main__":
    sys.exit(subprocess.call(["python3", "-m", "pytest", "-q", __file__]))
