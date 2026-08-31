"""pytest-bdd binding for features/verification_ledger.feature (crew#656 CP6)."""

import inspect
import json

from pytest_bdd import given, scenarios, then, when

from _verification_common import NOW, verification_ctx, load  # noqa: F401

scenarios("../features/verification_ledger.feature")
COLUMNS = (
    "claims_total",
    "claims_with_evidence",
    "claims_rejected_by_gate",
    "canary_windows_encountered",
    "canary_misses",
    "canary_passes",
    "retractions",
)


def sample_ledger(ctx, claims=None, audits=None, probes=None):
    led = load("verification-ledger")
    claims = (
        claims
        if claims is not None
        else [
            {
                "ts": "2026-08-31T05:00:00Z",
                "session": "a",
                "service": "backstage",
                "state": "MEASURED_OK",
                "kind": "command",
                "status": "ACCEPTED",
            },
            {
                "ts": "2026-08-31T05:01:00Z",
                "session": "b",
                "service": "canary",
                "state": "MEASURED_OK",
                "kind": "command",
                "status": "ACCEPTED",
            },
        ]
    )
    audits = (
        audits
        if audits is not None
        else [
            {"claim_ts": "2026-08-31T05:01:00Z", "session_id": "b", "outcome": "miss"},
            {"claim_ts": "2026-08-31T05:20:00Z", "session_id": "a", "outcome": "pass"},
        ]
    )
    ctx["led"] = led
    ctx["ledger"] = led.compute(claims, audits, probes or [], now=NOW, days=7)
    ctx["rows"] = {r["session_id"]: r for r in ctx["ledger"]["rows"]}
    return ctx["ledger"]


@given("the ledger")
def step_01(ctx):
    sample_ledger(ctx)


@given("the ledger page")
def step_02(ctx):
    sample_ledger(ctx)
    ctx["page"] = ctx["led"].render_markdown(ctx["ledger"])


@given("a session asserted a measured result")
def step_03(ctx):
    ctx["claims"] = [
        {
            "ts": "2026-08-31T05:00:00Z",
            "session": "a",
            "service": "backstage",
            "state": "MEASURED_OK",
            "kind": "command",
            "status": "ACCEPTED",
        }
    ]


@given("a later probe contradicts it")
def step_04(ctx):
    ctx["probes"] = [
        {
            "service": "backstage",
            "state": "MEASURED_FAIL",
            "observed_at": "2026-08-31T05:01:00Z",
        }
    ]


@given("a session is being considered for production work")
def step_05(ctx):
    sample_ledger(ctx)
    ctx["thresholds"] = {
        "min_claims": 1,
        "min_verification_rate": 0.5,
        "min_canary_windows": 1,
    }


@given("the ledger has just been created and every count is zero")
def step_06(ctx):
    led = load("verification-ledger")
    ctx["led"] = led
    ctx["zero"] = {
        **{k: 0 for k in COLUMNS},
        "session_id": "new",
        "verification_rate": 0.0,
        "canary_pass_rate": 0.0,
    }
    ctx["thresholds"] = {
        "min_claims": 0,
        "min_verification_rate": 0,
        "min_canary_windows": 0,
    }


@given("a session is recorded as having missed")
def step_07(ctx):
    sample_ledger(ctx)
    assert ctx["rows"]["b"]["canary_misses"] == 1


@when("eligibility is decided")
def step_08(ctx):
    led = ctx["led"]
    ctx["decision"] = {
        s: led.eligible(ctx["rows"][s], ctx["thresholds"]) for s in ctx["rows"]
    }
    ctx["source"] = inspect.getsource(led.eligible) + inspect.getsource(led.hook)


@when("eligibility is decided for any session")
def step_09(ctx):
    ctx["decision"] = {
        "new": ctx["led"].eligible(ctx["zero"], ctx["thresholds"]),
        "nothresholds": ctx["led"].eligible(ctx["zero"], None),
        "norow": ctx["led"].eligible(None, ctx["thresholds"]),
    }


@then(
    "it holds, per session identity, the claims made, the claims carrying evidence, the claims refused, the canary windows met, the misses, the passes and the retractions"
)
def step_10(ctx):
    assert set(ctx["rows"]) == {"a", "b"}
    for r in ctx["rows"].values():
        assert all(c in r for c in COLUMNS), r
    assert ctx["ledger"]["window_days"] == 7


@then("a retraction is recorded against that session")
def step_11(ctx):
    sample_ledger(ctx, claims=ctx["claims"], audits=[], probes=ctx["probes"])
    assert ctx["rows"]["a"]["retractions"] == 1


@then("it is one table sorted by misses, highest first")
def step_12(ctx):
    page = ctx["page"]
    assert page.count("| session |") == 1
    assert page.index("| b |") < page.index("| a |")
    misses = [r["canary_misses"] for r in ctx["ledger"]["rows"]]
    assert misses == sorted(misses, reverse=True)


@then("a session can read its own row")
def step_13(ctx):
    led = ctx["led"]
    path = ctx["tmp"] / "verification-ledger.json"
    path.write_text(json.dumps(ctx["ledger"]))
    loaded = led.load_ledger(path)
    row = next(r for r in loaded["rows"] if r["session_id"] == "a")
    assert row["canary_passes"] == 1


@then("it is read from the ledger")
def step_14(ctx):
    assert ctx["decision"]["a"][0] is True and ctx["decision"]["b"][0] is False, ctx[
        "decision"
    ]


@then("the session's own account of its record is not consulted")
def step_15(ctx):
    src = ctx["source"]
    for word in ("transcript", "input(", "tool_response", "self_report"):
        assert word not in src, word
    assert "load_ledger" in src


@then("none qualifies")
def step_16(ctx):
    assert all(v[0] is False for v in ctx["decision"].values()), ctx["decision"]


@then("it is not stopped")
def step_17(ctx):
    src = inspect.getsource(ctx["led"])
    for word in ("os.kill", "SIGTERM", "SIGKILL", "terminate("):
        assert word not in src, word


@then("the only consequence is the row and what the row gates")
def step_18(ctx):
    ok, why = ctx["led"].eligible(
        ctx["rows"]["b"], {"min_claims": 1, "min_verification_rate": 0.5}
    )
    assert ok is False and "max_canary_misses" in why
