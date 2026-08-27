"""crew#527 CP3: the board assigns. An alive session (feed handoff in the last 2h) holding no
claim gets the top of the finish-first rank; a session holding a claim keeps it and gets nothing
new; a claim 24h old with no box ticked since the board last saw it is released and re-ranked;
auto-objective hands a session its own assignment before the rank."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estate_board as eb

NOW = eb._ts("2026-08-27T18:00Z")
H = 3600


def _i(n, body="", claim=None):
    c = [{"body": f"CLAIM {claim[1]} session {claim[0]} lane code: x"}] if claim else []
    return {"number": n, "title": "t", "labels": [], "assignees": [], "comments": c, "body": body}


FEED = ("## 2026-08-27T17:30:00Z · session aaaaaaaa · lane code\n🟡 x\n"
        "## 2026-08-27T17:40:00Z · session bbbbbbbb · lane hermes\n🟡 y\n"
        "## 2026-08-27T09:00:00Z · session cccccccc · lane code\n🟡 old\n")


def test_alive_is_a_feed_handoff_in_the_window():
    assert eb.alive_sessions(FEED, NOW) == {"aaaaaaaa": "code", "bbbbbbbb": "hermes"}
    assert eb.alive_sessions("", NOW) == {}


def test_idle_alive_sessions_get_the_rank_in_order_and_holders_keep_theirs():
    issues = [_i(1, "- [x] a\n- [ ] b"), _i(2, ""), _i(3, "- [ ] a", claim=("bbbbbbbb", "2026-08-27T17:00:00Z"))]
    r = eb.assign(issues, {"aaaaaaaa": "code", "bbbbbbbb": "hermes"}, NOW, {}, post=False)
    assert r["assigned"] == [("aaaaaaaa", 1)]          # top of the rank, one per idle session
    assert r["held"] == {"bbbbbbbb": [3]} and r["released"] == []


def test_a_stale_claim_with_no_tick_is_released_and_a_moving_one_is_kept():
    stuck = _i(5, "- [ ] a", claim=("dddddddd", "2026-08-25T17:00:00Z"))
    moving = _i(6, "- [x] a\n- [ ] b", claim=("eeeeeeee", "2026-08-25T17:00:00Z"))
    fresh = _i(7, "- [ ] a", claim=("ffffffff", "2026-08-27T17:00:00Z"))
    seen = {5: (0, NOW - 30 * H), 6: (0, NOW - 30 * H), 7: (0, NOW - 30 * H)}
    r = eb.assign([stuck, moving, fresh], {}, NOW, seen, post=False)
    assert r["released"] == [5]
    assert r["held"] == {"eeeeeeee": [6], "ffffffff": [7]}
    # no baseline yet: the board cannot say nothing moved, so it holds
    r2 = eb.assign([_i(8, "", claim=("gggggggg", "2026-08-25T17:00:00Z"))], {}, NOW, {}, post=False)
    assert r2["released"] == [] and r2["held"] == {"gggggggg": [8]}


def test_assignment_for_is_the_open_claim_this_session_holds():
    issues = [_i(1, "- [ ] a", claim=("aaaaaaaa", "t")), _i(2, "- [x] a", claim=("bbbbbbbb", "t")), _i(3)]
    assert eb.assignment_for("aaaaaaaa-rest-of-id", issues)["number"] == 1
    assert eb.assignment_for("bbbbbbbb", issues) is None        # all ticked: a close-chore
    assert eb.assignment_for("zzzzzzzz", issues) is None
    assert eb.claimed_by(issues[0]) == ("aaaaaaaa", "t") and eb.claimed_by(issues[2]) is None


def test_auto_objective_reads_the_assignment_first():
    src = (Path(__file__).resolve().parent / "auto-objective.py").read_text()
    assert "board.assignment_for(session) or board.next_unclaimed()" in src


def test_the_baseline_is_the_oldest_seen_row_with_the_current_count(tmp_path):
    """code-99 REWORK on claude-guards#166: the board writes a `seen` row every turn, so the newest
    row can never be 24h old and the stale release never fired. Three daily rows, same count."""
    import json
    led = tmp_path / "ledger.jsonl"
    rows = [{"guard": "board", "event": "seen", "item": 5, "ticked": 0, "ts": "2026-08-25T18:00:00Z"},
            {"guard": "board", "event": "seen", "item": 5, "ticked": 0, "ts": "2026-08-26T18:00:00Z"},
            {"guard": "board", "event": "seen", "item": 5, "ticked": 0, "ts": "2026-08-27T17:00:00Z"},
            {"guard": "board", "event": "seen", "item": 6, "ticked": 0, "ts": "2026-08-25T18:00:00Z"},
            {"guard": "board", "event": "seen", "item": 6, "ticked": 1, "ts": "2026-08-27T17:00:00Z"},
            {"guard": "other", "event": "seen", "item": 7, "ticked": 0, "ts": "2026-08-25T18:00:00Z"}]
    led.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    seen = eb._last_boxes_seen(led)
    assert seen[5] == (0, eb._ts("2026-08-25T18:00Z"))       # oldest row of the unbroken run
    assert seen[6] == (1, eb._ts("2026-08-27T17:00Z"))       # the count moved: the run restarts
    assert 7 not in seen
    stuck = _i(5, "- [ ] a", claim=("dddddddd", "2026-08-25T17:00:00Z"))
    moved = _i(6, "- [x] a\n- [ ] b", claim=("eeeeeeee", "2026-08-25T17:00:00Z"))
    r = eb.assign([stuck, moved], {}, NOW, seen, post=False)
    assert r["released"] == [5] and r["held"] == {"eeeeeeee": [6]}


def test_blind_exits_3_so_a_missing_verb_is_never_a_healthy_finding(tmp_path):
    # code-2f on idp#450: argparse exits 2 on an unknown verb; a scheduler row that
    # treats 2 as BLIND would log a picker without `assign` as healthy.
    import subprocess
    script = str(Path(eb.__file__))
    env = {**os.environ, "ESTATE_FEED": str(tmp_path / "no-feed.md"), "ESTATE_BOARD_FIXTURE": str(tmp_path / "board.json")}
    (tmp_path / "board.json").write_text("[]")
    blind = subprocess.run([sys.executable, script, "assign", "--dry-run"], env=env, capture_output=True, text=True, check=False)
    assert blind.returncode == 3, blind.stdout + blind.stderr
    bad = subprocess.run([sys.executable, script, "no-such-verb"], env=env, capture_output=True, text=True, check=False)
    assert bad.returncode == 2
