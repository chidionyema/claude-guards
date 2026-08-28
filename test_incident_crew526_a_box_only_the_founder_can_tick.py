"""Founder, 2026-08-28: "should be waiting on [me] unless its physical action [machines] cannot do".

issue_dod.py stamped "Founder used it and confirmed (receipt: the comment or message where he said
so)" on every issue ticket-gate opened (crew#527 CP4). A box no machine can ever tick is a
permanent open item by construction, and on 2026-08-28 three built-and-proved issues -- crew#52,
crew#307 (a P0) and crew#484 -- were open on that line and nothing else, filed by the closer under
`no_rule` alongside 118 issues nobody had started.

Two things are pinned here: the template no longer manufactures that debt, and the closer counts
the debt that already exists instead of burying it."""
import re

import estate_board as b
import issue_dod as dod


def _i(n, body):
    return {"number": n, "title": f"t{n}", "body": body, "labels": [], "assignees": [],
            "comments": [], "created_at": "2026-08-01T00:00:00Z"}


LEGACY = f"- [x] Built: yes\n- [x] Proved: yes\n- [ ] {dod.LEGACY_FOUNDER_BOX}\n"


def test_the_template_no_longer_asks_for_something_only_the_founder_can_give():
    assert dod.has_dod(dod.DOD_BOXES)
    assert dod.LEGACY_FOUNDER_BOX not in dod.DOD_BOXES
    assert dod.USED_BOX in dod.DOD_BOXES
    # the third box still asks for use, not just a merge: that is what the receipt stood for
    assert "Used" in dod.DOD_BOXES and "Built" in dod.DOD_BOXES and "Proved" in dod.DOD_BOXES


def test_built_and_proved_but_for_the_founder_box_is_not_unstarted_work():
    assert b.awaiting_receipt(_i(1, LEGACY))
    r = b.close_pass([_i(1, LEGACY)], now=0.0, seen={}, cwd=".", post=False)
    assert r["awaiting_receipt"] == 1
    assert r["no_rule"] == 0, "finished work must not be filed with work nobody has started"


def test_an_issue_nobody_started_is_still_no_rule():
    r = b.close_pass([_i(2, "- [ ] Built\n- [ ] Proved\n- [ ] Used\n")], now=0.0, seen={}, cwd=".", post=False)
    assert r["no_rule"] == 1 and r["awaiting_receipt"] == 0


def test_a_second_unticked_box_means_the_work_is_not_finished():
    body = LEGACY + "- [ ] CP9 something real is still outstanding\n"
    assert not b.awaiting_receipt(_i(3, body))


def test_the_word_founder_in_a_box_is_not_enough_the_line_must_be_the_stamp():
    """The regression this function was written after: a filter on the word "founder" misfiled
    crew#345 ("zero founder interaction for 24h") and crew#527 ("after 7 days") as his to close.
    Both are ours."""
    for ours in ("Prove it: a real cluster health check runs with zero founder interaction for 24h",
                 "CP5 Receipt: after 7 days, science/velocity.jsonl shows closed/day rising",
                 "CP4 Founder receipt: he reads the ready count and says so."):
        assert not b.awaiting_receipt(_i(4, f"- [x] a\n- [ ] {ours}\n")), ours


def test_the_counter_reaches_the_science_log_and_the_printed_line(tmp_path):
    import json
    p = tmp_path / "closer.jsonl"
    b.log_close_pass(b.close_pass([_i(1, LEGACY)], now=0.0, seen={}, cwd=".", post=False), 1, str(p))
    assert json.loads(p.read_text().splitlines()[0])["awaiting_receipt"] == 1


def test_only_one_copy_of_the_legacy_line_exists_in_the_repo():
    """estate_board imports it from issue_dod; a second literal would drift silently."""
    src = re.sub(r"#.*", "", open(b.__file__).read())
    assert dod.LEGACY_FOUNDER_BOX not in src
