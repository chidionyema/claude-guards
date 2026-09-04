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
        "rule_guard", os.path.join(HERE, "rule-guard.py")
    )
    spec = importlib.util.spec_from_loader("rule_guard", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_a_merge_with_no_literal_number_outside_any_repo_is_refused(tmp_path):
    mod = _load()
    mod._ACTIVE_REPO = str(
        tmp_path
    )  # empty dir: rev-parse fails, gh has nothing to view
    verdict = mod.rule_merge_red_pr(
        'gh pr merge --repo o/r --squash --delete-branch "$PR"'
    )
    assert verdict is not None and "no literal PR number" in verdict


def test_a_merge_naming_its_number_still_takes_the_graded_path(monkeypatch):
    mod = _load()
    seen = {}

    def fake_verdict(pr, states, escaped, main_red, main_red_marker, auto=False):
        seen["pr"] = pr
        return None

    monkeypatch.setattr(mod, "_merge_verdict", fake_verdict)
    monkeypatch.setattr(
        mod, "_pr_check_states", lambda pr, cmd=None: [("qa", "SUCCESS")]
    )
    monkeypatch.setattr(mod, "_main_red_refusal", lambda: None)
    assert mod.rule_merge_red_pr("gh pr merge 100 --squash") is None
    assert seen["pr"] == "100"


if __name__ == "__main__":
    sys.exit(subprocess.call(["python3", "-m", "pytest", "-q", __file__]))
