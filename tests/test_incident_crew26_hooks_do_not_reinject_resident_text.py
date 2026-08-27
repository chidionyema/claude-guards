"""Incident test, crew#26 (2026-08-27): two SessionStart/PostCompact hooks re-injected 1.24 MB of
text one session already held (28 compactions x 44 KB), and nothing counted compactions. Rung 4:
one test per bug, asserting the rule, not the code."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_incident_crew26_laws_block_is_a_pointer_unless_asked_for_the_copy(tmp_path):
    env = dict(os.environ, MEMORY_LOOP_LAWS="pointer")
    stdin = json.dumps({"hook_event_name": "PostCompact", "transcript_path": str(tmp_path / "none.jsonl")})
    out = subprocess.run([sys.executable, str(HERE / "memory-loop.py")], input=stdin, env=env,
                         capture_output=True, text=True).stdout
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "[laws]" in ctx and "AGENTS.md" in ctx
    assert len(ctx) < 4000, len(ctx)
    env["MEMORY_LOOP_LAWS"] = "full"
    out = subprocess.run([sys.executable, str(HERE / "memory-loop.py")], input=stdin, env=env,
                         capture_output=True, text=True).stdout
    assert len(json.loads(out)["hookSpecificOutput"]["additionalContext"]) > len(ctx)


def test_incident_crew26_rulings_keep_verbatim_and_stay_under_16kb():
    fr = _load("friction-relay")
    block = fr.render_rulings()
    rows = json.load(open(HERE / "rulings.json"))["rulings"]
    for r in rows:
        assert r["verbatim"] in block, r["id"]
    assert len(block) < 16000, len(block)
    assert fr._first_sentence("Never do X. Also Y.") == "Never do X."


def test_incident_crew26_compactions_are_a_strong_signal(tmp_path):
    cg = _load("context-guard-hook")
    path = tmp_path / "t.jsonl"
    lines = [json.dumps({"type": "user", "isCompactSummary": True}) for _ in range(cg.COMPACT_WARN)]
    lines.append(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 5}}}))
    path.write_text("\n".join(lines) + "\n")
    assert cg.compactions(path) == cg.COMPACT_WARN
    signals, strong, fires = cg.assess(0, 0, 0, 0, cg.compactions(path))
    assert fires and strong and any("compactions" in s for s in signals)
    _, strong, fires = cg.assess(0, 0, 0, 0, cg.COMPACT_WARN - 1)
    assert not fires and not strong
