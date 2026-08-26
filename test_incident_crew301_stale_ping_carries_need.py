"""Incident crew#301 (2026-08-26): a session sat BLOCKED for four hours and the only pings the
founder got read "BLOCKED on crew#301 for 243m, nobody validated it". He asked "how do i know i
need to unblock?". Rule: the stale-BLOCKED ping quotes the Need: and Who: lines of the BLOCKED
comment, and names a comment without them rogue. Rung 4 (incident). Both ways."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("auto_objective", os.path.join(HERE, "auto-objective.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_ping_carries_need_and_who():
    body = "BLOCKED: OCI session expired\nTried: oci session validate\nError: Abort\nNeed: oci session authenticate --profile-name estate-bootstrap\nWho: founder"
    text = _mod.stale_blocked_text(301, 14580, body)
    assert "Need: oci session authenticate --profile-name estate-bootstrap" in text
    assert "Who: founder" in text
    assert "nobody validated" not in text


def test_ping_names_a_blocker_without_need_rogue():
    text = _mod.stale_blocked_text(301, 600, "BLOCKED: stuck")
    assert "rogue" in text and "issues/301" in text
