"""crew#490 (2026-08-27): a pull request that conflicted with main had zero check runs for 40
minutes; a close/reopen and an empty commit changed nothing, because GitHub creates no
pull_request run when it cannot build the merge ref. rule-guard refused the merge (correct) and
told the session to wait for CI (wrong: there was nothing to wait for). Rung 4, incident, both
ways: the no-checks refusal names the conflict cause and the one command that reads it; a refusal
for a red or pending check does not, since there the checks exist.
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _load():
    loader = importlib.machinery.SourceFileLoader("rule_guard", os.path.join(HERE, "rule-guard.py"))
    spec = importlib.util.spec_from_loader("rule_guard", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_incident_crew490_no_checks_refusal_names_the_conflict_and_the_command():
    rg = _load()
    msg = rg._merge_refusal("490", [])
    assert msg and "NO checks" in msg
    assert "conflicts" in msg and "gh pr view 490 --json mergeable" in msg


def test_incident_crew490_a_pending_or_red_check_does_not_blame_a_conflict():
    rg = _load()
    for states in ([("qa", "PENDING")], [("qa", "FAILURE")]):
        msg = rg._merge_refusal("490", states)
        assert msg and "conflicts" not in msg, msg
