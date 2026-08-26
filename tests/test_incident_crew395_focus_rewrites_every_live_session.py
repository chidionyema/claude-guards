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
