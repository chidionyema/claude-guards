#!/usr/bin/env python3
"""crew#656 CP0. The two failures of 2026-08-29 in test form, plus the false-refusal
cases that decide whether this guard is usable or gets routed around.

LAW 45: the mistake ends as a guard no session can walk past, proved over every instance.
The instances here are every banned token in the founder's spec section 2, both of the
day's real failures, and the exemptions that keep the guard off correct work (LAW 38: a
guard that refuses correct work is an outage).
"""

import importlib.util
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sv = (
    importlib.import_module("state_vocabulary")
    if (HERE / "state_vocabulary.py").exists()
    else None
)
if sv is None:  # pragma: no cover
    pytest.skip("state_vocabulary.py not present", allow_module_level=True)


def _load_broadcast():
    spec = importlib.util.spec_from_file_location(
        "estate_broadcast_under_test", HERE / "estate-broadcast.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- the real failures


def test_the_2126z_failure_is_refused():
    """A session told the founder a service was up on a peer's self-report."""
    hits = sv.offending_tokens(
        "Correction: Backstage is up. code-07 signed in at 21:24Z."
    )
    assert hits, "the exact sentence that caused the 21:22 incident must be refused"
    # ruff S105 reads `x["token"] == "literal"` as a hardcoded credential, so the
    # refused words are lifted into a plainly-named list before being compared.
    refused_words = [hit["token"] for hit in hits]
    assert refused_words[0] == "up"


def test_the_refusal_names_the_offending_token():
    """The spec requires the token be named, so the refusal is actionable."""
    with pytest.raises(sv.Refusal) as exc:
        sv.check("the catalogue is down")
    assert "'down'" in str(exc.value)


def test_the_refusal_offers_the_three_permitted_states():
    with pytest.raises(sv.Refusal) as exc:
        sv.check("langfuse is healthy")
    text = str(exc.value)
    for state in sv.PERMITTED_STATES:
        assert state in text


def test_a_peer_report_is_named_as_a_lead_in_the_refusal():
    with pytest.raises(sv.Refusal) as exc:
        sv.check("signoz is fine")
    assert "LEAD (unverified" in str(exc.value)


# ---------------------------------------------------------------- every instance


@pytest.mark.parametrize("token", sv.BANNED)
def test_every_banned_token_is_refused(token):
    """The sweep. A guard proved on one token is a guard that missed six."""
    assert sv.offending_tokens(f"the router is {token}")


@pytest.mark.parametrize("token", sv.BANNED)
def test_negation_does_not_launder_a_banned_token(token):
    assert sv.offending_tokens(f"the router is not {token}")


def test_hedges_do_not_launder_a_banned_token():
    for hedge in ("still", "now", "back"):
        assert sv.offending_tokens(f"the catalogue is {hedge} up")


# ---------------------------------------------------------------- not an outage


@pytest.mark.parametrize(
    "sentence",
    [
        "the founder asked to bring the feed guard back up for review",
        "a working directory is not a claim about a service",
        "the down payment cleared this morning",
        "keep the operational model in one file",
        "read the fine print before signing",
        "up to date with origin/main",
        "a broken link in the README",
    ],
)
def test_ordinary_english_is_not_refused(sentence):
    """LAW 38. A guard that refuses correct work is an outage, and sessions route
    around a guard that cries wolf, which leaves the real claim unguarded."""
    assert sv.offending_tokens(sentence) == []


@pytest.mark.parametrize("state", sv.PERMITTED_STATES)
def test_the_permitted_states_pass(state):
    assert sv.offending_tokens(f"backstage is {state}") == []


def test_a_labelled_lead_passes():
    assert (
        sv.offending_tokens(
            "LEAD (unverified, source: code-07): a peer says the catalogue renders"
        )
        == []
    )


# ---------------------------------------------------------------- the gate itself


def test_the_broadcast_gate_refuses_a_banned_post():
    mod = _load_broadcast()
    refusal = mod._vocabulary_refusal({"message": "backstage is up"})
    assert refusal and "'up'" in refusal


def test_the_broadcast_gate_allows_a_measured_post():
    mod = _load_broadcast()
    assert (
        mod._vocabulary_refusal({"message": "backstage is MEASURED_OK, probe age 42s"})
        is None
    )


def test_the_override_exists_and_is_documented(monkeypatch):
    """Spec section 8 requires a manual override the founder can use."""
    mod = _load_broadcast()
    monkeypatch.setenv("ESTATE_VOCABULARY_OVERRIDE", "1")
    assert mod._vocabulary_refusal({"message": "backstage is up"}) is None


def test_a_broken_checker_fails_loud_and_open_not_closed(monkeypatch, capsys):
    """The founder-doc-capture lesson, encoded: this board is the channel by which the
    estate is told the gate is broken, so a config failure must not close it.

    Simulated the way it actually happens -- a checker present but broken (half-written,
    mid-edit, a syntax error landed) rather than a path trick the code correctly survives.
    """
    import sys as _sys
    import types

    mod = _load_broadcast()
    broken = types.ModuleType("state_vocabulary")  # importable, but has no check()
    monkeypatch.setitem(_sys.modules, "state_vocabulary", broken)

    assert mod._vocabulary_refusal({"message": "backstage is up"}) is None
    assert "GATE_UNAVAILABLE" in capsys.readouterr().err


def test_a_working_checker_still_refuses_after_the_broken_one(monkeypatch):
    """Proves the fail-open path is not sticky: the next post is graded again."""
    mod = _load_broadcast()
    assert mod._vocabulary_refusal({"message": "backstage is up"})


def test_the_guard_can_see_what_it_grades():
    """Refuses an empty sweep: a guard proving nothing reads identical to a clean pass."""
    assert len(sv.BANNED) == 7
    assert len(sv.REFUSES) >= 7 and len(sv.ALLOWS) >= 7
