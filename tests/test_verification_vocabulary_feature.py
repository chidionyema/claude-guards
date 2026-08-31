"""pytest-bdd binding for features/verification_vocabulary.feature (crew#656 CP0)."""

from pytest_bdd import given, parsers, scenarios, then, when

from _verification_common import verification_ctx, gate, load  # noqa: F401

scenarios("../features/verification_vocabulary.feature")
BANNED = ("up", "down", "healthy", "working", "fine", "operational", "broken")


def broadcast_refusal(ctx, message):
    return load("estate-broadcast")._vocabulary_refusal(
        {"from": "s-test", "kind": "note", "message": message}
    )


@given("a session is describing a service")
def step_01(ctx):
    ctx["vocab"] = load("state_vocabulary")


@then('the only states it may assert are "MEASURED_OK", "MEASURED_FAIL" and "UNKNOWN"')
def step_02(ctx):
    assert set(ctx["vocab"].PERMITTED_STATES) == {
        "MEASURED_OK",
        "MEASURED_FAIL",
        "UNKNOWN",
    }


@given(parsers.parse('a board post asserting a service is "{word}"'))
def step_03(ctx, word):
    ctx["message"] = f"backstage is {word}"
    ctx["word"] = word


@given("a post says the founder asked to bring a guard back up for review")
def step_04(ctx):
    ctx["message"] = "the founder asked to bring a guard back up for review"


@when("the broadcast gate reads it")
def step_05(ctx):
    ctx["refusal"] = broadcast_refusal(ctx, ctx["message"])


@then("the post is refused")
def step_06(ctx):
    assert ctx["refusal"], "the post went through"


@then("the post is not refused")
def step_07(ctx):
    assert ctx["refusal"] is None, ctx["refusal"]


@then("the refusal names the offending token")
def step_08(ctx):
    assert f"refused token: '{ctx['word']}'" in ctx["refusal"], ctx["refusal"]


@given(
    'the banned tokens are "up", "down", "healthy", "working", "fine", "operational" and "broken"'
)
def step_09(ctx):
    ctx["tokens"] = BANNED
    assert set(BANNED) <= set(load("state_vocabulary").BANNED)


@when("each is used in turn as an assertion about a service")
def step_10(ctx):
    ctx["refusals"] = {
        t: broadcast_refusal(ctx, f"langfuse is {t}") for t in ctx["tokens"]
    }


@then("each one is refused by name")
def step_11(ctx):
    for t, r in ctx["refusals"].items():
        assert r and f"refused token: '{t}'" in r, (t, r)


@given("a session has no probe result inside the freshness window")
def step_12(ctx):
    ctx["env"] = {
        "claim": "no probe of backstage inside the window",
        "state": "UNKNOWN",
        "service": "backstage",
    }


@when("it reports the state")
def step_13(ctx):
    gate(ctx, ctx["env"])


@then('it reports "UNKNOWN"')
def step_14(ctx):
    assert ctx["result"]["state"] == "UNKNOWN"


@then("the report is accepted without warning")
def step_15(ctx):
    assert ctx["refusal"] is None and "(gate:" not in ctx["text"]
