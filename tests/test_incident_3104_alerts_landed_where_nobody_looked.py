"""2026-08-29: every estate alert for four days went into a file with no reader.

`estate_alert.send_operator_alert` falls back to `~/.estate/alerts/inbox.jsonl` whenever
TELEGRAM_ALERT_CHANNEL is unset. It is unset. Measured that morning: 3,104 alerts had piled up in
that file since 08-25, the estate scanner going stale and every spend warning among them, and no
page anywhere rendered it. The sender returns True for those writes, so the path reads as
delivered end to end. His words: "i cant see ny innportannt nessages".

The board now serves /alerts. This proves the page exists, that it folds a repeated sentence into
one row rather than printing it 1,730 times, that it never folds two different alerts together,
and that an empty or missing inbox says so instead of 500-ing.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import board_serve as bs  # noqa: E402


def _inbox(tmp_path, rows):
    p = tmp_path / "inbox.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(p)


def test_the_incident_the_inbox_has_a_page_at_all():
    assert hasattr(bs, "_alerts_page") and hasattr(bs, "_alert_rows"), (
        "nothing renders ~/.estate/alerts/inbox.jsonl; alerts land where nobody looks"
    )
    src = open(os.path.join(HERE, "board_serve.py"), encoding="utf-8").read()
    assert '"/alerts"' in src, "the board does not route /alerts"


def test_a_sentence_said_1730_times_is_one_row_that_says_1730(tmp_path):
    now = time.time()
    rows = [{"ts": now + i, "source": "auto-objective.py",
             "text": f"BLOCKED on crew#488 for {i}m. No Need:/Who: line; the session is rogue."}
            for i in range(1730)]
    out = bs._alert_rows(_inbox(tmp_path, rows))
    assert len(out) == 1, f"the repeat is still {len(out)} rows in his view"
    assert out[0]["n"] == 1730, out[0]["n"]
    assert b"&times;1730" in bs._alerts_page(out), "the page hides how often it fired"


def test_two_different_alerts_are_never_folded_together(tmp_path):
    """The canary: folding is for display, and a fold that eats a real fault is the worse bug."""
    now = time.time()
    rows = [{"ts": now, "source": "estate_watch.py", "text": "ESTATE SCANNER STALE last scan 9h ago"},
            {"ts": now + 1, "source": "estate_cost_sentinel.py", "text": "Spend warning over the cap"}]
    out = bs._alert_rows(_inbox(tmp_path, rows))
    assert len(out) == 2, "two unrelated faults were folded into one row"
    assert out[0]["source"] == "estate_cost_sentinel.py", "newest is not first"


def test_a_missing_inbox_is_a_sentence_not_a_stack_trace(tmp_path):
    assert bs._alert_rows(str(tmp_path / "nothing.jsonl")) == []
    page = bs._alerts_page([])
    assert b"TELEGRAM_ALERT_CHANNEL" in page, (
        "an empty page must say where else the sender might be writing, or it reads as 'all quiet'"
    )


def test_a_corrupt_line_does_not_take_the_page_down(tmp_path):
    p = tmp_path / "inbox.jsonl"
    p.write_text('{"ts": 1, "source": "a", "text": "real"}\nnot json at all\n')
    assert len(bs._alert_rows(str(p))) == 1
