"""2026-08-29: the founder could not find a real message in his own alert view.

Measured that morning from ~/.estate/alerts/inbox.jsonl: 3,104 alerts, of which 2,609 were nine
distinct sentences repeated, and one single sentence -- "BLOCKED on crew#N for Nm. No Need:/Who:
line; the session is rogue." -- had been delivered 1,730 times. His words: "nosie eveyrwhere",
"i cant see ny innportannt nessages", "flooding ny view".

estate_alert had a debounce the whole time. It was opt-in, so every caller that named no
debounce_key repeated without limit, and the 84% of the inbox that was one guard nagging drowned
the estate scanner and the cost sentinel underneath it. This proves the sender now dedupes by the
words themselves, that a caller which names its own key still governs its own cadence, and that
two genuinely different alerts are never collapsed into one.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "estate"))
import estate_alert as ea  # noqa: E402


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    """A real send through the on-disk inbox path, with the debounce file also under tmp."""
    box = tmp_path / "inbox.jsonl"
    monkeypatch.setenv("ESTATE_ALERT_INBOX", str(box))
    monkeypatch.delenv("HERMES_ALERT_DM_FALLBACK", raising=False)
    monkeypatch.setattr(ea, "_DEBOUNCE", tmp_path / "debounce.json")
    monkeypatch.setattr(ea, "_env", lambda k: None)          # no channel, no token: inbox path
    monkeypatch.setattr(ea.telegram_ledger, "record", lambda *a, **k: None)
    return box


def _rows(box):
    return [json.loads(ln) for ln in box.read_text().splitlines() if ln.strip()]


def test_the_incident_the_same_sentence_is_not_delivered_twice(inbox):
    text = "BLOCKED on crew#488 for 41m. No Need:/Who: line; the session is rogue."
    assert ea.send_operator_alert(text) is True, "the first time must always get through"
    for _ in range(50):
        ea.send_operator_alert(text)
    assert len(_rows(inbox)) == 1, (
        f"one sentence reached the founder {len(_rows(inbox))} times; on 2026-08-29 it was 1,730"
    )


def test_the_same_sentence_with_a_different_minute_count_is_the_same_sentence(inbox):
    """The 1,730 were not byte-identical: the elapsed minutes ticked up in every one."""
    for m in range(1, 40):
        ea.send_operator_alert(f"BLOCKED on crew#488 for {m}m. No Need:/Who: line; the session is rogue.")
    assert len(_rows(inbox)) == 1, (
        "a counter inside the text made every repeat look new; that is how 9 sentences became 2,609"
    )


def test_two_different_alerts_are_still_two_alerts(inbox):
    """The canary. A debounce that swallows a real second fault is worse than the flood."""
    assert ea.send_operator_alert("ESTATE SCANNER STALE: last scan 9h ago") is True
    assert ea.send_operator_alert("Spend warning: Claude spend is over the daily cap") is True
    assert len(_rows(inbox)) == 2, "two unrelated faults were collapsed into one"


def test_a_caller_that_names_its_own_key_still_governs_its_own_cadence(inbox):
    """An explicit key keeps the 300s default, so a caller can page faster than the hourly floor."""
    ea.send_operator_alert("first", debounce_key="k", debounce_s=0)
    ea.send_operator_alert("second, same key, window already expired", debounce_key="k", debounce_s=0)
    assert len(_rows(inbox)) == 2, "an explicit debounce_key/debounce_s no longer decides"


def test_the_key_is_recorded_so_a_suppression_can_be_traced(inbox):
    ea.send_operator_alert("a fault worth a receipt")
    assert _rows(inbox)[0]["key"].startswith("auto:"), (
        "the derived key is not written to the inbox row, so nobody can tell why a repeat vanished"
    )
