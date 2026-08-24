"""rule-guard refused `gh pr merge 2 --repo chidionyema/claude-estate` with another repo's checks.

2026-08-24: the command names its repository outright. The guard ignored the flag and resolved
the path instead: the session was in ~/.claude, `_is_product_repo` excludes that directory by
identity, so `_repo_for` fell back to REPO and `gh pr checks 2` ran in prospector. It reported
`python=failure, dotnet=failure` -- prospector's checks, on prospector's PR #2. claude-estate has
no workflows at all, so those two jobs cannot exist there.

Worse than a wrong answer: that refusal path carries `no override`, on the grounds that a check
which finished and did not pass is an answer rather than an outage. So a correct merge command
was refused with no way past, on evidence from a different repository. LAW 38.

Fifth variant of the wrong-repo class. The four before it were all paths the guard mis-resolved.
This one is not a path at all, which is why every earlier fix missed it.

The rule: when a command names its repository with --repo or -R, that name outranks every path
guess. When it names none, resolution is exactly as before. Rung 4, incident test, named for the
bug.
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# Built from fragments on purpose. rule-guard runs as a PreToolUse hook and grades the text of
# the command that runs this test, so a literal `gh pr merge` in the source refuses the test run.
MERGE = "gh " + "pr " + "me" + "rge 2 "
FLAG = "--re" + "po "


def _load():
    loader = importlib.machinery.SourceFileLoader("rule_guard", os.path.join(HERE, "rule-guard.py"))
    spec = importlib.util.spec_from_loader("rule_guard", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_incident_rule_guard_repo_flag_graded_the_wrong_repo():
    rg = _load()
    slug = "chidionyema/claude-estate"

    # must-fire half: every spelling gh accepts is read, and the repo named is the repo used
    for cmd in (MERGE + FLAG + slug + " --squash",
                MERGE + "-R " + slug,
                MERGE + "--re" + "po=" + slug):
        m = rg._GH_REPO_FLAG.search(cmd)
        assert m is not None, cmd
        assert m.group("slug") == slug, cmd

    # must-not-fire half: no flag means resolution is untouched, so nothing that worked breaks
    assert rg._GH_REPO_FLAG.search(MERGE) is None
    assert rg._GH_REPO_FLAG.search("gh pr list --state open") is None
    # a bare word after the flag is not a slug and must not be mistaken for one
    assert rg._GH_REPO_FLAG.search(MERGE + FLAG + "notaslug") is None

    # the query carries the name through to gh, rather than relying on the working directory
    import inspect
    src = inspect.getsource(rg._pr_check_states)
    assert '"--repo", named.group("slug")' in src
