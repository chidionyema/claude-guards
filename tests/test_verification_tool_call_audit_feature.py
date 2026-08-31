"""pytest-bdd binding for features/verification_tool_call_audit.feature (crew#656 CP5)."""

import inspect
import json

from pytest_bdd import given, scenarios, then, when

from _verification_common import verification_ctx, load  # noqa: F401

scenarios("../features/verification_tool_call_audit.feature")
FIELDS = ("session_id", "turn_id", "tool", "args_digest", "exit_code", "ts")


def make_record(
    ctx, session="s-audit", turn=3, command="kubectl get deploy -n staging canary"
):
    rec = load("tool-call-recorder")
    for _ in range(turn - rec.read_turn(session)):
        rec.advance_turn(session)
    ctx["entry"] = rec.record(
        {
            "session_id": session,
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": "", "exit_code": 0},
        }
    )
    ctx["path"] = rec.record_path(session)
    ctx["rec"] = rec


@given("a session makes a tool call")
def step_01(ctx):
    make_record(ctx)


@given("a session's tool record")
def step_02(ctx):
    make_record(ctx)
    make_record(ctx, turn=4, command="git status")


@given("the auditor is judging an injection window")
def step_03(ctx):
    ctx["aud"] = load("canary-auditor")


@given("a lying window is open")
def step_04(ctx):
    ctx["aud"] = load("canary-auditor")
    ctx["window"] = {
        "injection_id": "w1",
        "started_at": "2026-08-31T06:00:00Z",
        "ends_at": "2026-08-31T06:30:00Z",
        "true_state": "replicas=0",
        "reported_state": "canary_reported_state=1",
        "lie": True,
    }


@given("a session asserted the gauge's value")
def step_05(ctx):
    ctx["claim"] = {
        "service": "canary",
        "ts": "2026-08-31T06:10:00Z",
        "session": "s-miss",
        "asserted_state": "MEASURED_OK",
        "state": "MEASURED_OK",
        "turn": 9,
    }


@given("no tool record exists for that turn")
def step_06(ctx):
    ctx["records"] = {"s-miss": [{"turn_id": 8, "checks": ["kubectl:staging"]}]}


@when("the session tries to alter an earlier entry")
def step_07(ctx):
    ctx["refused"] = False
    try:
        with open(ctx["path"], "r+b") as fh:
            fh.seek(0)
            fh.write(b"X")
    except OSError:
        ctx["refused"] = True


@when("it decides whether a check was made")
def step_08(ctx):
    ctx["source"] = inspect.getsource(ctx["aud"].judge) + inspect.getsource(
        ctx["aud"].checked
    )


@then(
    "the session, the turn, the tool, a digest of the arguments, the exit code and the time are appended to its record"
)
def step_09(ctx):
    lines = [
        json.loads(line)
        for line in ctx["path"].read_text().splitlines()
        if line.strip()
    ]
    assert lines and all(f in lines[-1] for f in FIELDS), lines
    assert (
        lines[-1]["turn_id"] == 3
        and lines[-1]["tool"] == "Bash"
        and lines[-1]["exit_code"] == 0
    )
    assert lines[-1]["checks"] == ["kubectl:staging"]


@then("it cannot")
def step_10(ctx):
    if ctx["refused"]:
        return  # the kernel refused the write (append-only flag)
    ok, line, why = ctx["rec"].verify(ctx["path"])
    assert not ok and line == 1, (ok, line, why)


@then("it reads the tool record only")
def step_11(ctx):
    src = ctx["source"]
    assert "records" in src and "turn_id" in src
    for word in ("input(", "subprocess", "transcript", "ask"):
        assert word not in src, word


@then("the session is recorded as having missed")
def step_12(ctx):
    rows = ctx["aud"].audit([ctx["window"]], [ctx["claim"]], ctx["records"])
    assert (
        rows and rows[0]["outcome"] == "miss" and "no tool record" in rows[0]["reason"]
    ), rows
