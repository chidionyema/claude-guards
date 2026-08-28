"""crew#52: on 2026-08-23 aiden raised 9 alerts and 7 were WAITING lines from ONE empty
`prospector-cli-cwd-slot-0` session that had no work in it.

An empty transcript is not a stalled agent, it is an empty slot, and alerting on it is what makes
the channel worth muting -- which is the real cost, because the two alerts that mattered were in
the same nine. 2bc3968 fixed `state_of` and nothing pinned it: there was no incident test, so the
next person to reorder those branches would put the noise back and no run would say so (LAW 45).

The ordering is the fragile part. `state_of` returns RUNNING for anything idle under 120s before
it ever looks at the text, so the empty-slot branch only protects sessions that have gone quiet --
exactly the ones that would otherwise age into WAITING. A test that only checked `state_of("")`
without an idle time would pass against a version that had lost the fix entirely.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("aiden_mod", HERE / "aiden" / "aiden.py")
aiden = importlib.util.module_from_spec(spec)
sys.modules["aiden_mod"] = aiden
spec.loader.exec_module(aiden)

HOUR = 3600.0


def _row(session="s1", slug="prospector-cli-cwd-slot-0", text="", idle=HOUR):
    return {"session": session, "slug": slug, "text": text, "idle": idle,
            "cache_write": 0, "cache_read": 0, "usd": 0.0, "recent": []}


def test_a_session_that_has_never_said_anything_is_idle_however_long_it_sits():
    for idle in (11 * 60, HOUR, 5 * HOUR):
        assert aiden.state_of(_row(idle=idle)) == "IDLE", idle


def test_whitespace_is_not_speech():
    assert aiden.state_of(_row(text="   \n\n  \t\n")) == "IDLE"


def test_a_session_that_did_say_something_and_went_quiet_is_still_waiting():
    """The fix must not have bought silence by deleting the alert."""
    assert aiden.state_of(_row(text="working on the render", idle=11 * 60)) == "WAITING"


def test_the_quiet_branch_is_reached_at_all(monkeypatch):
    """RUNNING short-circuits before the text is read, so pin that the empty check is downstream
    of it: a fresh empty session is RUNNING, an aged one is IDLE, never WAITING."""
    assert aiden.state_of(_row(idle=30)) == "RUNNING"
    aged = (aiden.WAITING_MINUTES + 1) * 60
    assert aiden.state_of(_row(idle=aged)) == "IDLE"


def test_the_2026_08_23_shape_raises_no_waiting_alert(monkeypatch, tmp_path):
    """One empty slot polled repeatedly is what produced 7 of the 9 alerts."""
    monkeypatch.setattr(aiden, "HOME", str(tmp_path))          # no ticket files, no gh
    empty = [_row(session=f"s{i}", idle=HOUR + i) for i in range(7)]
    real = [_row(session="real", slug="idp", text="BLOCKED: needs a key", idle=HOUR)]
    monkeypatch.setattr(aiden.observe, "sessions", lambda h: (empty + real, []))
    out = aiden.alerts()
    assert not [a for a in out if a.startswith("WAITING")], out
    assert len([a for a in out if a.startswith("BLOCKED")]) == 1, out
    assert len(out) == 1, f"9 alerts became 1; got {len(out)}: {out}"
