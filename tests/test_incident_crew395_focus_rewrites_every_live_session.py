"""Incident test (rung 4), crew#395: the founder said "forget about fly, you have one mission"
and a session stayed on crew#66 because ~/.claude/state/goal/<session>.json still said so; it
then reported BLOCKED on the idle-guard's claim list instead of rewriting its own goal.

Paired in one run: `goal-guard.py --focus` rewrites a state file that moved today and leaves a
three-day-old one alone; the idle-guard claim list under that focus never carries crew#66.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GG = os.path.join(HERE, "goal-guard.py")


def _state(home, sess, goal):
    d = os.path.join(home, ".claude", "state", "goal")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{sess}.json")
    with open(p, "w") as f:
        json.dump({"goal": goal, "run": 0, "last_progress": "", "last_progress_at": 0, "fired": 0, "calls": 0}, f)
    return p


def _read(p):
    with open(p) as f:
        return json.load(f)


def test_incident_crew395_focus_rewrites_live_sessions_and_spares_stale_ones(tmp_path):
    home = str(tmp_path)
    live = _state(home, "live-aaaa", "crew#66: eradicate fly")
    stale = _state(home, "stale-bbbb", "crew#13: retire hermes")
    old = time.time() - 3 * 86400
    os.utime(stale, (old, old))
    env = dict(os.environ, HOME=home)
    r = subprocess.run([sys.executable, GG, "--focus", "crew#284: finish KINI", "--source", "test"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "focus set for 1 live session(s)" in r.stdout, r.stdout
    assert _read(live)["goal"] == "crew#284: finish KINI"
    assert _read(live)["prev_goal"] == "crew#66: eradicate fly"
    assert _read(stale)["goal"] == "crew#13: retire hermes"
    focus = _read(os.path.join(home, ".claude", "state", "goal", "FOCUS.json"))
    assert focus["text"] == "crew#284: finish KINI" and focus["sessions"] == ["live-aaaa"]
    # the empty line is refused, not laundered into a rewrite of every session
    r2 = subprocess.run([sys.executable, GG, "--focus", "  "], env=env, capture_output=True, text=True)
    assert r2.returncode == 1 and _read(live)["goal"] == "crew#284: finish KINI"


def test_incident_crew395_claim_list_under_a_focus_never_offers_the_off_mission_item():
    import importlib.util
    spec = importlib.util.spec_from_file_location("goal_guard", GG)
    gg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gg)
    items = [{"number": 66, "title": "eradicate fly io"}, {"number": 284, "title": "KINI delivered"},
             {"number": 306, "title": "hard execution chain for kini"}]
    kept = [i["number"] for i in gg.focus_filter(items, "crew#284: finish KINI")]
    assert kept == [284, 306]
    assert gg.focus_filter(items, "") == items


def test_incident_crew395_a_founder_focus_line_on_the_board_rewrites_goals_once(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("goal_guard", GG)
    gg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gg)
    gg.STATE_DIR = tmp_path / "goal"
    gg.LEDGER = tmp_path / "ledger.jsonl"
    gg.write_state("live-cccc", {"goal": "crew#66: eradicate fly", "run": 0, "last_progress": "",
                                 "last_progress_at": 0, "fired": 0, "calls": 0})
    spec2 = importlib.util.spec_from_file_location("board_deliver", os.path.join(HERE, "board-deliver.py"))
    bd = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(bd)
    entries = [{"from": "founder", "text": "FOCUS: crew#284: finish KINI", "ts": "2026-08-26T23:30:00Z"},
               {"from": "some-session", "text": "FOCUS: crew#66: fly again", "ts": "2026-08-26T23:31:00Z"}]
    assert bd.apply_focus(entries, gg) == 1
    assert gg.read_state("live-cccc")["goal"] == "crew#284: finish KINI"
    # a second session delivering the same board is not a second rewrite
    assert bd.apply_focus(entries, gg) == 0
    assert sum(1 for l in gg.LEDGER.read_text().splitlines() if '"kind":"focus"' in l) == 1


def test_incident_crew395_blocked_on_a_direction_the_focus_already_gives_is_refused(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("dod_guard", os.path.join(HERE, "dod-guard.py"))
    dg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dg)
    dg.FOCUS_FILE = tmp_path / "FOCUS.json"
    asks = ("BLOCKED: the board has 138 items.\nTried: the claim list.\nError: none.\n"
            "Need: the founder to decide which item comes first.\nWho: founder.\n")
    hand = ("BLOCKED: vault seed needs a tap.\nTried: gh workflow run vault-seed.yml.\n"
            "Error: touch required.\nNeed: a YubiKey tap from the founder.\nWho: founder.\n")
    assert dg.offences(asks) == []                      # no focus: nothing to hold it to
    dg.FOCUS_FILE.write_text(json.dumps({"text": "crew#284: finish KINI"}))
    out = dg.offences(asks)
    assert len(out) == 1 and "crew#284: finish KINI" in out[0]
    assert dg.offences(hand) == []                      # a physical hand is not a direction
