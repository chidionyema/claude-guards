"""crew#506 CP2 (2026-08-27): with a CI watcher in flight, every end of turn drew the idle-guard v2
board-claim prompt ("claim one and start it now"), forcing a context switch mid-task. The consultant
review the founder approved: a run in flight is a reason to end the turn, not idleness; the harness
re-invokes the session when the run reports. The escape is graded: line 1 opens WAITING: and names a
run still in flight. Both ways: a WAITING: naming no live run is still the old idle claim."""
from __future__ import annotations

import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("auto_objective", HERE / "auto-objective.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_waiting_that_names_the_live_run_is_an_escape() -> None:
    m = _mod()
    assert m.waiting_on("WAITING: CI on idp#412; run bh3xjsmi3 reports when it settles.\n\n---\nmore", ["bh3xjsmi3"])
    assert m.waiting_on("**WAITING:** merge watcher bh3xjsmi3", ["zzz", "bh3xjsmi3"])


def test_waiting_that_names_no_live_run_is_still_idle() -> None:
    m = _mod()
    assert not m.waiting_on("WAITING: for things to happen", ["bh3xjsmi3"])
    assert not m.waiting_on("WORKING: bh3xjsmi3 is running", ["bh3xjsmi3"]), "only WAITING: is the escape"
    assert not m.waiting_on("", ["bh3xjsmi3"])


def test_dod_guard_leaves_a_waiting_reply_untouched() -> None:
    spec = importlib.util.spec_from_file_location("dod_guard", HERE / "scripts" / "archive" / "dod-guard.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    assert d.first_word("WAITING: run abc in flight") == "WAITING"
