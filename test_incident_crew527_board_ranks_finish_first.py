"""crew#527 CP2 (founder 2026-08-27: "we have many features half done ... prioritisation"): the
board's next item was the oldest unclaimed number, so a fresh idea outranked nothing and a
feature at 8/9 boxes waited behind it. Rule: finish-first. Both ways: most-ticked first; P0
before P1 before none at equal fraction; founder-request before not; blocked-on an OPEN issue
last, blocked-on a closed one not blocked; no checklist ranks as 0 ticked; ties by number."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estate_board as eb  # noqa: E402


def _i(n, body="", labels=()):
    return {"number": n, "title": "t", "labels": list(labels), "assignees": [], "comments": [], "body": body}


def test_most_ticked_first_then_priority_then_founder_then_age():
    issues = [
        _i(10),                                             # nothing ticked, oldest
        _i(11, "- [x] a\n- [x] b\n- [ ] c"),                 # 2/3
        _i(12, "- [x] a\n- [ ] b", ["P1"]),                  # 1/2 P1
        _i(13, "- [x] a\n- [ ] b", ["P0"]),                  # 1/2 P0
        _i(14, "- [x] a\n- [ ] b", ["founder-request"]),     # 1/2 founder
        _i(15, "- [x] a\n- [ ] b"),                          # 1/2 plain, younger than 16
        _i(16, "- [x] a\n- [ ] b"),
        _i(17, "- [ ] a"),                                   # 0/1
    ]
    assert [i["number"] for i in eb.unclaimed(issues)] == [11, 13, 12, 14, 15, 16, 10, 17]


def test_blocked_on_an_open_issue_ranks_last_and_a_closed_blocker_does_not_block():
    issues = [_i(20, "- [x] a\n- [x] b\n- [ ] c", ["P0"]), _i(21), _i(22, "Blocked-on: #21\n- [x] a\n- [x] b\n- [ ] c", ["P0"]),
              _i(23, "Blocked-on: #999 (closed)\n- [x] a\n- [ ] b")]
    assert [i["number"] for i in eb.unclaimed(issues)] == [20, 23, 21, 22]
    assert eb.blocked_on(issues[2]) == {21} and eb.boxes(issues[0]) == (2, 1)


def test_all_ticked_is_a_close_chore_not_next_work() -> None:
    """code-2f REWORK on cg#164: frac 1.0 put a finished issue above every half-done one."""
    issues = [
        _i(5, "- [x] a\n- [x] b"),
        _i(6, "- [x] a\n- [ ] b"),
        _i(7, ""),
    ]
    assert [i["number"] for i in eb.unclaimed(issues)] == [6, 7]
    assert eb.all_ticked(issues[0]) and not eb.all_ticked(issues[1])
    assert not eb.all_ticked(issues[2])
