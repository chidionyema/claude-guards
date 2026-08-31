"""Shared fixtures for the crew#656 verification-layer bindings (features/verification_*.feature)."""

import datetime as dt
import importlib.util
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 8, 31, 6, 0, tzinfo=dt.timezone.utc)


def load(name):
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), HERE / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(name="ctx")
def verification_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIM_GATE_LOG", str(tmp_path / "claims.jsonl"))
    monkeypatch.setenv("TOOL_CALL_RECORD_DIR", str(tmp_path / "tool-calls"))
    monkeypatch.setenv("ESTATE_DIR", str(tmp_path))
    monkeypatch.delenv("ESTATE_VOCABULARY_OVERRIDE", raising=False)
    monkeypatch.delenv("ESTATE_PROBES_DIR", raising=False)
    monkeypatch.delenv("CLAIM_GATE_FRESHNESS_SECONDS", raising=False)
    return {"tmp": tmp_path, "now": NOW, "prom": lambda q: [{"value": [0, "1"]}]}


def stamp(seconds_ago=30):
    return (NOW - dt.timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def command_evidence(exit_code=0, seconds_ago=30, **extra):
    return {
        "kind": "command",
        "command": "bin/idp-prove backstage",
        "exit_code": exit_code,
        "output": "PASS",
        "observed_at": stamp(seconds_ago),
        **extra,
    }


def gate(ctx, env, surface="board"):
    cg = load("claim_gate")
    text = "state of the service:\n" + cg.render(env)
    out, refusal = cg.gate_text(
        text,
        session="s-test",
        surface=surface,
        now=ctx["now"],
        prom=ctx["prom"],
        log=ctx["tmp"] / "claims.jsonl",
    )
    ctx.update(text=out, refusal=refusal)
    blocks = cg.envelopes_in(out)
    ctx["result"] = blocks[0][1] if blocks else None
    return refusal


def claims_logged(ctx):
    p = ctx["tmp"] / "claims.jsonl"
    return (
        [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        if p.exists()
        else []
    )
