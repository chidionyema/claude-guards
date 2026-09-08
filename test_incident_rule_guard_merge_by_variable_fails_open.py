"""rule-guard let `gh pr merge "$PR"` through while the PR's qa check was still running.

2026-08-24: a command merged crew PR #99 with the number held in a shell variable. The
hook's text shows `"$PR"`, so `_GH_MERGE_NUM` matched nothing and `rule_merge_red_pr`
fell back to resolving the PR from the checkout. Every failure path in that fallback
returned None — a pass — against a docstring that promises the rule fails CLOSED. The
merge landed, and the qa check concluded FAILURE on code already on main.

The rule: a `gh pr merge` whose PR the guard cannot attribute is refused, never waved
through. Rung 4, incident test, named for the bug.
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


def test_a_merge_with_no_literal_number_outside_any_repo_is_refused(tmp_path):
    mod = _load()
    mod._ACTIVE_REPO = str(tmp_path)   # empty dir: rev-parse fails, gh has nothing to view
    verdict = mod.rule_merge_red_pr(
        'gh pr merge --repo o/r --squash --delete-branch "$PR"')
    assert verdict is not None and "no literal PR number" in verdict


def test_a_merge_naming_its_number_still_takes_the_graded_path(monkeypatch):
    mod = _load()
    seen = {}

    def fake_verdict(pr, states, escaped, main_red, main_red_marker):
        seen["pr"] = pr
        return None

    monkeypatch.setattr(mod, "_merge_verdict", fake_verdict)
    monkeypatch.setattr(mod, "_pr_check_states", lambda pr, cmd=None: [("qa", "SUCCESS")])
    monkeypatch.setattr(mod, "_main_red_refusal", lambda: None)
    assert mod.rule_merge_red_pr("gh pr merge 100 --squash") is None
    assert seen["pr"] == "100"


if __name__ == "__main__":
    sys.exit(subprocess.call(["python3", "-m", "pytest", "-q", __file__]))


def test_a_repo_flag_with_a_space_does_not_hide_the_number():
    """`-R owner/repo 252` names PR 252, and the guard must read it as such.

    2026-09-08: it did not. The flag-skipping loop consumed `-R` and then met
    `chidionyema/claude-guards`, which is not a flag, so it stopped before the number.
    The rule fell back to the checkout, resolved idp#2407 -- a different pull request in
    a different repository -- and refused the merge on THAT PR's red checks. A guard
    grading the wrong subject is worse than one that grades nothing: it produces a
    confident, specific, wrong refusal (LAW 38).

    `--repo=x` matched and `-R x` did not, so the defect was invisible to anyone who
    happened to write the equals sign.
    """
    mod = _load()
    for cmd, want in (
        ("gh pr merge -R chidionyema/claude-guards 252 --squash --delete-branch", "252"),
        ("gh pr merge --repo chidionyema/claude-guards 253 --squash", "253"),
        # every shape that already worked, unchanged
        ("gh pr merge 252", "252"),
        ("gh pr merge --repo=chidionyema/claude-guards 252", "252"),
        ("gh pr merge --squash 252", "252"),
        ("gh pr merge 2440 --squash --delete-branch", "2440"),
        ("gh api -X PUT repos/o/r/pulls/324/merge", "324"),
    ):
        m = mod._GH_MERGE_NUM.search(cmd)
        assert m is not None, cmd
        assert (m.group(1) or m.group(2)) == want, cmd
