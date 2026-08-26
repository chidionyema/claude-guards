"""Incident test (rung 4), crew#52: 7 of 9 aiden alerts on 2026-08-23 were WAITING lines from
one empty prospector-cli-cwd-slot-0 session that had never said anything.

Executes the scenario in features/hard_execution_chain.feature against aiden.state_of.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "aiden"))
import aiden  # noqa: E402


def _row(text, idle_s):
    return {"text": text, "idle": idle_s, "session": "s", "slug": "slot-0"}


def test_incident_crew52_empty_session_not_waiting():
    assert aiden.state_of(_row("", 30 * 60)) == "IDLE"
    assert aiden.state_of(_row("   \n", 30 * 60)) == "IDLE"
    assert aiden.state_of(_row("WORKING: on it", 30 * 60)) == "WAITING"
    assert aiden.state_of(_row("BLOCKED: need x", 30 * 60)) == "BLOCKED"
    assert aiden.state_of(_row("", 10)) == "RUNNING"
