"""crew#488 (2026-08-29): idp#675 was queued with

    gh pr merge 675 --repo chidionyema/idp --squash --auto --delete-branch

and GitHub merged it at 00:35:33Z. The portability-drill run for that head sha (33223840305,
created 00:32:35Z) was still going and concluded FAILURE. main's drill gate was out for roughly
thirty minutes: every pull request touching platform/** or clusters/** was graded against a floor
the tree could not meet.

rule-guard already refuses a merge whose checks are pending, and it did its job -- at the instant
the command was typed. `--auto` does not merge at that instant. It queues, and GitHub fires it
when the REQUIRED contexts go green. chidionyema/idp requires four (offline-gate, bdd,
security-scan, operating-model-gate) out of the thirteen a pull request runs, so `hydrate` and
`k3s` were never waited for. A fence that grades at time T cannot fence an action at T+n.

Rung 4, incident, both ways: `--auto` is refused when a check exists that GitHub will not wait
for, and allowed when the required set already covers every check the pull request runs -- because
a guard that refuses correct work is an outage (LAW 38).
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))

#: The states idp#675 carried, with the four contexts chidionyema/idp actually requires.
IDP_675 = [("offline-gate", "SUCCESS"), ("bdd", "SUCCESS"), ("security-scan", "SUCCESS"),
           ("operating-model-gate / operating-model-gate", "SUCCESS"),
           ("hydrate", "SUCCESS"), ("k3s", "SUCCESS"), ("spec-gate", "SUCCESS")]
IDP_REQUIRED = {"offline-gate", "bdd", "security-scan", "operating-model-gate / operating-model-gate"}
CMD = "gh pr merge 675 --repo chidionyema/idp --squash --auto --delete-branch"


def _load():
    loader = importlib.machinery.SourceFileLoader("rule_guard", os.path.join(HERE, "rule-guard.py"))
    spec = importlib.util.spec_from_loader("rule_guard", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_auto_is_refused_and_names_the_checks_github_would_not_wait_for():
    rg = _load()
    msg = rg._auto_merge_refusal("675", IDP_675, IDP_REQUIRED, CMD)
    assert msg, "the exact command that took main's drill gate out was allowed"
    assert "hydrate" in msg and "k3s" in msg, msg
    # and it does not blame a check GitHub really does wait for
    assert "bdd" not in msg.split("instead")[0], msg


def test_the_refusal_hands_over_the_command_that_replaces_it():
    rg = _load()
    msg = rg._auto_merge_refusal("675", IDP_675, IDP_REQUIRED, CMD)
    assert "gh pr checks 675" in msg and "gh pr merge 675 --squash" in msg, msg
    assert "no override" in msg, "a queued merge cannot be graded now, whoever means it"


def test_auto_is_allowed_when_every_check_the_pr_runs_is_required():
    """LAW 38: this is not a ban on --auto. It is a ban on --auto outrunning a check."""
    rg = _load()
    states = [("bdd", "SUCCESS"), ("offline-gate", "SUCCESS")]
    assert rg._auto_merge_refusal("1", states, {"bdd", "offline-gate"}, CMD) is None


def test_a_merge_without_auto_is_not_this_rules_business():
    rg = _load()
    plain = "gh pr merge 675 --repo chidionyema/idp --squash --delete-branch"
    assert rg._auto_merge_refusal("675", IDP_675, IDP_REQUIRED, plain) is None


def test_unreadable_required_set_fails_closed():
    """The rest of this fence fails closed on an unknown verdict; so does this."""
    rg = _load()
    msg = rg._auto_merge_refusal("675", IDP_675, None, CMD)
    assert msg and "could not be read" in msg, msg


def test_auto_survives_a_green_board_because_the_states_are_stale_by_construction():
    """The whole point: every state above is SUCCESS and the merge is still refused.

    idp#675's board was green when the command was typed. The drill registered afterwards, so
    _merge_verdict -- which grades only what exists now -- had nothing to object to.
    """
    rg = _load()
    assert all(s == "SUCCESS" for _, s in IDP_675)
    assert rg._merge_verdict("675", IDP_675, escaped=False, main_red=None, fixing_main=False) is None
    assert rg._auto_merge_refusal("675", IDP_675, IDP_REQUIRED, CMD)


def test_merge_red_intended_does_not_open_it():
    rg = _load()
    escaped_cmd = CMD + " # merge-red-intended"
    assert rg._auto_merge_refusal("675", IDP_675, IDP_REQUIRED, escaped_cmd), \
        "the outage hatch is for GitHub not answering, not for a merge nobody can grade yet"


def test_the_regex_catches_auto_only_on_the_merge_segment():
    rg = _load()
    assert rg._GH_MERGE_AUTO.search("gh pr merge 7 --auto")
    assert rg._GH_MERGE_AUTO.search("gh pr merge 7 --squash --auto --delete-branch")
    assert not rg._GH_MERGE_AUTO.search("gh pr merge 7 --squash")
    # a different command in the same line must not arm the rule
    assert not rg._GH_MERGE_AUTO.search("gh pr merge 7 --squash; gh run watch --auto")
