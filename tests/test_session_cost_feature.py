"""pytest-bdd binding for features/session_cost.feature (crew#26). The scenarios are the spec;
each step runs the hook it names. Rung 4 (incident, one per bug) expressed as the executable
spec the spec-gate asks for (R29, crew#297)."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

HERE = pathlib.Path(__file__).resolve().parents[1]
scenarios("../features/session_cost.feature")


def _load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ctx(tmp_path):
    return {"tmp": tmp_path}


def _memory_loop(ctx, laws):
    env = dict(os.environ, HOME=str(ctx["tmp"]))
    if laws is None:
        env.pop("MEMORY_LOOP_LAWS", None)
    else:
        env["MEMORY_LOOP_LAWS"] = laws
    stdin = json.dumps({"hook_event_name": ctx["event"], "transcript_path": str(ctx["tmp"] / "none.jsonl")})
    out = subprocess.run([sys.executable, str(HERE / "memory-loop.py")], input=stdin, env=env,
                         capture_output=True, text=True).stdout
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


@given("a session start or a compaction")
def _(ctx):
    (ctx["tmp"] / ".claude").mkdir()
    (ctx["tmp"] / ".claude" / "CLAUDE.md").write_text(
        "# LAW 1 — Put the fire out first\n\n" + "the law text, longer than the pointer. " * 40 + "\n\n# How to work\n\nx\n")
    ctx["event"] = "PostCompact"


@when("memory-loop runs with MEMORY_LOOP_LAWS unset")
def _(ctx):
    ctx["pointer"] = _memory_loop(ctx, None)


@then("the [laws] block is under 2 KB and names the ~/AGENTS.md table already in the window")
def _(ctx):
    block = ctx["pointer"].split("[laws]", 1)[1].split("\n\n", 1)[0]
    assert "AGENTS.md" in block and len(block) < 2048, len(block)


@then("MEMORY_LOOP_LAWS=full restores the full copy")
def _(ctx):
    assert len(_memory_loop(ctx, "full")) > len(ctx["pointer"])


@given(parsers.parse("rulings.json with {n:d} rulings"))
def _(ctx, n):
    ctx["rows"] = json.load(open(HERE / "rulings.json"))["rulings"]
    assert len(ctx["rows"]) >= n, len(ctx["rows"])


@when("friction-relay renders them")
def _(ctx):
    ctx["block"] = _load("friction-relay").render_rulings()


@then("every verbatim quote is present")
def _(ctx):
    for r in ctx["rows"]:
        assert r["verbatim"] in ctx["block"], r["id"]


@then("the block is under 16 KB")
def _(ctx):
    assert len(ctx["block"]) < 16000, len(ctx["block"])
