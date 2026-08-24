"""rule-guard refused `cd ~/dev/code/idp && gh pr merge 6` by reading another repo's PR #6.

2026-08-24: the leading `cd` used `~`. `_expand` filled only variables assigned inside the
command, so the path stayed literal, `_worktree_root` found no repo, `_repo_for` fell back to
REPO (prospector) and `gh pr checks 6` ran there. The merge was green in idp and blocked
anyway. Fourth variant of the wrong-repo class. Rung 4, incident test, named for the bug.

The rule: any path the shell would resolve (`~`, `$HOME`, `${HOME}`) resolves the same way
in the guard. Proved both ways: a resolvable path lands on the cd target; a path that is not
a repository still falls back exactly as before.
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _load():
    loader = importlib.machinery.SourceFileLoader(
        "rule_guard", os.path.join(HERE, "rule-guard.py"))
    spec = importlib.util.spec_from_loader("rule_guard", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_incident_rule_guard_tilde_cd_graded_the_wrong_repo(monkeypatch):
    rg = _load()
    with tempfile.TemporaryDirectory() as home:
        repo = os.path.join(home, "dev", "code", "idp")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q", repo], check=True)
        monkeypatch.setenv("HOME", home)
        real = os.path.realpath(repo)
        for cmd in (f"cd ~/dev/code/idp && gh pr merge 6",
                    f"cd $HOME/dev/code/idp && gh pr merge 6",
                    f"cd ${{HOME}}/dev/code/idp && gh pr merge 6"):
            assert os.path.realpath(rg._repo_for(cmd, "/")) == real, cmd
        # must-not-fire half: a path that is not a repo still falls back, never a crash
        assert rg._repo_for("cd ~/nowhere && gh pr merge 6", "/") == rg.REPO
