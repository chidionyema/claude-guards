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
    # CI has no ~/.claude/CLAUDE.md; the hook reads $HOME/.claude/CLAUDE.md, so give it one.
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("# LAW 1 — Put the fire out first\n\n" + "the law text, longer than the pointer. " * 40 + "\n\n# How to work\n\nx\n")
    env = dict(os.environ, MEMORY_LOOP_LAWS="pointer", HOME=str(tmp_path))
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
    signals, strong, fires = cg.assess(0, 0, 0, 0, cg.COMPACT_WARN)
    assert fires and strong and any("compactions" in s for s in signals)
    _, strong, fires = cg.assess(0, 0, 0, 0, cg.COMPACT_WARN - 1)
    assert not fires and not strong


def test_incident_crew584_meaning_lines_ride_only_the_newest_rulings():
    """crew#584: 44 rulings rendered 15,993 of the 16,000 cap; the 45th turned CI red.
    Every verbatim stays; the => line is carried for the newest MEANING_ROWS only."""
    import json, os, tempfile
    fr = _load("friction-relay")
    rows = [{"id": "R%d-x" % i, "date": "2026-08-28", "verbatim": "v%d" % i, "meaning": "m%d." % i}
            for i in range(1, 41)]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"rulings": rows}, fh)
    saved = fr.RULINGS
    try:
        fr.RULINGS = fh.name
        block = fr.render_rulings()
    finally:
        fr.RULINGS = saved
        os.unlink(fh.name)
    assert all(r["verbatim"] in block for r in rows)
    assert block.count("      => ") == fr.MEANING_ROWS
    assert "=> m40." in block and "=> m1." not in block
