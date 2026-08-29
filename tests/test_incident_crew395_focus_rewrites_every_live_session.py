"""Incident test (rung 4), crew#395: the founder said "forget about fly, you have one mission"
and a session stayed on crew#66 because ~/.claude/state/goal/<session>.json still said so; it
then reported BLOCKED on a claim list instead of taking the direction he had just given.

crew#638 (founder triage, 2026-08-29) deleted goal-guard, goal_focus and auto-objective, so the
per-session goal files this incident was about no longer exist and cannot go stale. What survives
is the half that was never a guess: a FOCUS: line on the board becomes the standing focus, and
policy/reply.rego refuses a reply that asks him for a direction that focus already gives. Both
halves are graded here; the two tests that drove the deleted CLI went with it.
"""
import importlib.util
import json
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_incident_crew395_a_founder_focus_line_on_the_board_is_written_once(tmp_path):
    """A founder FOCUS: line lands in FOCUS.json; nobody else's does; twice is once."""
    bd = _load("board_deliver", "board-deliver.py")
    focus_file = tmp_path / "goal" / "FOCUS.json"
    entries = [{"from": "founder", "text": "FOCUS: crew#284: finish KINI", "ts": "2026-08-26T23:30:00Z"},
               {"from": "some-session", "text": "FOCUS: crew#66: fly again", "ts": "2026-08-26T23:31:00Z"}]
    assert bd.apply_focus(entries, focus_file) == 1
    assert json.loads(focus_file.read_text())["text"] == "crew#284: finish KINI"
    # a second session delivering the same board is not a second write
    assert bd.apply_focus(entries, focus_file) == 0
    # a session's own FOCUS: line never becomes the founder's standing focus
    assert bd.apply_focus([entries[1]], focus_file) == 0
    assert json.loads(focus_file.read_text())["text"] == "crew#284: finish KINI"


def test_incident_crew395_an_empty_focus_line_never_clears_the_standing_one(tmp_path):
    bd = _load("board_deliver", "board-deliver.py")
    focus_file = tmp_path / "goal" / "FOCUS.json"
    bd.apply_focus([{"from": "founder", "text": "FOCUS: crew#284: finish KINI", "ts": "1"}], focus_file)
    assert bd.apply_focus([{"from": "founder", "text": "FOCUS:    ", "ts": "2"}], focus_file) == 0
    assert json.loads(focus_file.read_text())["text"] == "crew#284: finish KINI"


def test_incident_crew395_the_adapter_reads_the_file_the_board_writes(tmp_path, monkeypatch):
    """The write and the read are in two scripts. This is the one test that puts them together,
    because that seam is where crew#623's class of defect lives: each side correct, agreeing on
    nothing. board-deliver writes, opa-hook.standing_focus reads, same path under one HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    bd = _load("board_deliver", "board-deliver.py")
    oh = _load("opa_hook", "opa-hook.py")
    written = tmp_path / ".claude" / "state" / "goal" / "FOCUS.json"
    assert bd.apply_focus([{"from": "founder", "text": "FOCUS: crew#284: finish KINI", "ts": "1"}], written) == 1
    assert oh.standing_focus() == "crew#284: finish KINI"


def test_incident_crew395_blocked_on_a_direction_the_focus_already_gives_is_refused():
    """crew#398: the rule is policy/reply.rego, evaluated through opa-hook.denials with the focus
    the adapter hands it. BLIND (skipped) without opa, never green."""
    if not shutil.which("opa"):
        pytest.skip("BLIND: opa not installed")
    oh = _load("opa_hook", "opa-hook.py")
    asks = ("BLOCKED: the board has 138 items.\nTried: the claim list.\nError: none.\n"
            "Need: the founder to decide which item comes first.\nWho: founder.\n")
    hand = ("BLOCKED: vault seed needs a tap.\nTried: gh workflow run vault-seed.yml.\n"
            "Error: touch required.\nNeed: a YubiKey tap from the founder.\nWho: founder.\n")
    q = oh.REPLY_QUERY
    assert oh.denials({"event": "Stop", "reply": asks, "focus": ""}, q) == []          # no focus: nothing to hold it to
    out = oh.denials({"event": "Stop", "reply": asks, "focus": "crew#284: finish KINI"}, q)
    assert len(out) == 1 and "crew#284: finish KINI" in out[0]
    assert oh.denials({"event": "Stop", "reply": hand, "focus": "crew#284: finish KINI"}, q) == []  # a hand is not a direction
