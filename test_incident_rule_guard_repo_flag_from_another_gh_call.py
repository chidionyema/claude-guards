"""rule-guard applied a -R from a later `gh issue comment` to the merge's check query.

2026-08-26, session d636e984: `cd ~/dev/code/estate-secrets && gh pr merge 8 --squash ...;
gh issue comment 227 -R chidionyema/crew -b "..."` was refused with `PR #8 is not green --
qa=failure`. estate-secrets#8 had two green checks; crew#8 carries qa=FAILURE. `_pr_check_states`
took the first --repo/-R anywhere in the command line, and that flag belonged to a different gh
invocation three segments later. The refusal path carries `no override`, so a correct merge was
blocked on another repository's evidence until the merge itself was given `-R`.

Sixth variant of the wrong-repo class. The rule: only the shell segment that holds the merge may
name the merge's repository. A flag in any other segment is that command's business. Rung 4,
incident test, named for the bug.
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# Built from fragments on purpose: rule-guard grades the text of the command that runs this test.
MERGE = "gh " + "pr " + "me" + "rge 8 --squash --delete-branch"
OTHER = "gh issue comment 227 -R chidionyema/crew -b 'x'"
OWN = "chidionyema/estate-secrets"


def _load():
    loader = importlib.machinery.SourceFileLoader("rule_guard", os.path.join(HERE, "rule-guard.py"))
    spec = importlib.util.spec_from_loader("rule_guard", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_incident_rule_guard_repo_flag_from_another_gh_call():
    rg = _load()

    # must-not-fire half: the flag on a different gh call is not the merge's flag
    for cmd in (f"cd ~/dev/code/estate-secrets && {MERGE} 2>&1 | tail -1; {OTHER}",
                f"{MERGE}\n{OTHER}",
                f"{MERGE} || {OTHER}"):
        assert rg._merge_repo_flag(cmd) is None, cmd

    # must-fire half: a flag on the merge itself still wins, wherever the merge sits in the line
    for cmd in (f"{MERGE} -R {OWN}; {OTHER}",
                f"{OTHER}; {MERGE} --repo {OWN}",
                f"cd /tmp && {MERGE} --repo={OWN} | tail -1"):
        m = rg._merge_repo_flag(cmd)
        assert m is not None and m.group("slug") == OWN, cmd

    # the check query reads the flag through the scoped helper, not the whole line
    import inspect
    assert "_merge_repo_flag(cmd)" in inspect.getsource(rg._pr_check_states)


if __name__ == "__main__":
    test_incident_rule_guard_repo_flag_from_another_gh_call()
    print("ok    rule-guard: a -R on another gh call no longer names the merge's repository")
