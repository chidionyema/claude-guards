"""pytest-bdd binding for features/verification_claim_envelope.feature (crew#656 CP2)."""

from pytest_bdd import given, scenarios, then, when

from _verification_common import command_evidence, verification_ctx, gate, load  # noqa: F401

scenarios("../features/verification_claim_envelope.feature")


def measured(ctx, state="MEASURED_OK", evidence=None):
    ctx["env"] = {
        "claim": "backstage probe passed",
        "state": state,
        "service": "backstage",
        "evidence": evidence if evidence is not None else command_evidence(),
    }


@given("a claim stating a measured result")
def step_01(ctx):
    measured(ctx)


@given("a claim stating a measured pass")
def step_02(ctx):
    measured(ctx, "MEASURED_OK")


@given("the claim carries no evidence")
def step_03(ctx):
    ctx["env"]["evidence"] = {"kind": "none"}


@given("a claim whose evidence is older than the service's freshness window")
def step_04(ctx):
    measured(ctx, evidence=command_evidence(seconds_ago=400))


@given("a claim citing a query that returns no result")
def step_05(ctx):
    measured(
        ctx,
        evidence={
            "kind": "metric",
            "query": 'probe_state{service="nowhere"}',
            "observed_at": command_evidence()["observed_at"],
        },
    )
    ctx["prom"] = lambda q: []


@given("its evidence is a command that exited non-zero")
def step_06(ctx):
    ctx["env"]["evidence"] = command_evidence(exit_code=1)


@given("the probe records that the post-sign-in identifier was absent")
def step_07(ctx):
    ctx["env"]["evidence"] = command_evidence(
        probe_identifier_present=0, output="HTTP 302 -> /auth/sign-in"
    )


@given('a claim whose state is "UNKNOWN"')
def step_08(ctx):
    ctx["env"] = {
        "claim": "no probe inside the window",
        "state": "UNKNOWN",
        "service": "backstage",
    }


@given("the gate cannot reach the metric store")
def step_09(ctx):
    ctx["prom"] = lambda q: None
    measured(
        ctx,
        evidence={
            "kind": "metric",
            "query": 'probe_state{service="backstage"}',
            "observed_at": command_evidence()["observed_at"],
        },
    )


@given("a session has been told by a peer that a service is reachable")
def step_10(ctx):
    ctx["peer"] = "session-7f3a"


@given("a session is replying to the founder and asserting service state")
def step_11(ctx):
    measured(ctx, evidence={"kind": "none"})


@when("the gate reads it")
def step_12(ctx):
    gate(ctx, ctx["env"])


@when("a session tries to post a claim")
def step_13(ctx):
    gate(ctx, ctx["env"])


@when("it repeats that on the board")
def step_14(ctx):
    cg = load("claim_gate")
    # what a peer's word may be written as, and what it may not
    lead = {
        "claim": "LEAD (unverified): peer says backstage answered",
        "state": "UNKNOWN",
        "service": "backstage",
        "lead": True,
        "source": ctx["peer"],
    }
    ctx["lead_ok"] = cg.validate(lead, now=ctx["now"], prom=ctx["prom"]).ok
    ctx["unsourced"] = cg.validate(
        {**lead, "source": ""}, now=ctx["now"], prom=ctx["prom"]
    )
    ctx["measured_lead"] = cg.validate(
        {**lead, "state": "MEASURED_OK", "evidence": {"kind": "none"}},
        now=ctx["now"],
        prom=ctx["prom"],
    )


@when("the reply is composed")
def step_15(ctx):
    dod = load("dod-guard")
    cg = load("claim_gate")
    ctx["reply_offences"] = dod.claim_guard(
        "INVENTORY: backstage\n" + cg.render(ctx["env"]), "founder-reply"
    )[1]
    ctx["bare_offences"] = dod.claim_guard(
        "INVENTORY: backstage is MEASURED_OK, no block", "founder-reply"
    )[1]
    gate(ctx, ctx["env"], surface="founder-reply")


@then("the claim is refused")
def step_16(ctx):
    assert ctx["refusal"], "the claim was accepted"


@then("the claim is accepted with no evidence")
def step_17(ctx):
    assert (
        ctx["refusal"] is None
        and ctx["result"].get("evidence", {"kind": "none"})["kind"] == "none"
    )


@then('the state is rewritten to "UNKNOWN"')
def step_18(ctx):
    assert ctx["refusal"] is None and ctx["result"]["state"] == "UNKNOWN", (
        ctx["refusal"],
        ctx["result"],
    )


@then("the author is warned")
def step_19(ctx):
    assert "(gate:" in ctx["text"] and "rewritten to UNKNOWN" in ctx["text"]


@then("it must label the statement a lead and name the peer as the source")
def step_20(ctx):
    assert (
        ctx["lead_ok"]
        and not ctx["unsourced"].ok
        and "source" in ctx["unsourced"].reason
    )


@then("the statement may not carry a measured state")
def step_21(ctx):
    assert not ctx["measured_lead"].ok and "LEAD" in ctx["measured_lead"].reason


@then("the refusal says the gate is unavailable, distinct from a refused claim")
def step_22(ctx):
    assert (
        ctx["refusal"].startswith("GATE_UNAVAILABLE")
        and "CLAIM_REJECTED" not in ctx["refusal"]
    )


@then(
    "at least one channel that does not depend on the gate can report the gate is broken"
)
def step_23(ctx):
    # the board lets a post through when the gate cannot load (estate-broadcast._claim_refusal),
    # and a command envelope or UNKNOWN never touches the metric store
    src = (load("claim_gate").HERE / "estate-broadcast.py").read_text()
    assert "GATE_UNAVAILABLE" in src and "Post allowed" in src
    cg = load("claim_gate")
    ctx["env"]["evidence"] = command_evidence()
    assert cg.validate(ctx["env"], now=ctx["now"], prom=lambda q: None).ok


@then("the same evidence rule applies as on the board")
def step_24(ctx):
    assert ctx["refusal"] and ctx["reply_offences"] and ctx["bare_offences"]
    assert ctx["reply_offences"][0].split("\n")[0] == ctx["refusal"].split("\n")[0]
