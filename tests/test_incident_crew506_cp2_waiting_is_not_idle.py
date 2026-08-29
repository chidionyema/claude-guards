"""crew#506 CP2 (2026-08-27): with a CI watcher in flight, every end of turn drew the idle-guard v2
board-claim prompt ("claim one and start it now"), forcing a context switch mid-task. The escape was
graded by auto-objective.waiting_on: line 1 opens WAITING: and names a run still in flight.

crew#638 (founder triage, 2026-08-29) deleted both idle-guard and auto-objective, so there is no
prompt left to escape from and waiting_on has no caller. What is left of this incident is that
WAITING: is one of the five legal first words of a reply, which dod-guard reads off line 1 -- a
parse, not a judgement, which is why that half survived the triage and this test still runs it."""
from __future__ import annotations

import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]


def test_dod_guard_reads_waiting_as_the_first_word_of_the_reply() -> None:
    spec = importlib.util.spec_from_file_location("dod_guard", HERE / "dod-guard.py")
    d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
    assert d.first_word("WAITING: run abc in flight") == "WAITING"
    assert d.first_word("**WAITING:** merge watcher bh3xjsmi3") == "WAITING"
