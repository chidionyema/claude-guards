"""crew#13 / crew#53 incident, 2026-08-27T02:11Z: the LAW 24 guard's own commit was refused
by the ticket-default commit-msg hook because its subject named no issue, so drift stayed
uncommitted and the board carried "tracked.py could not commit".

Rule: the guard's commit subject satisfies the same pattern ticket-default applies. The
pattern is read from the hook itself, so the two cannot drift apart silently.
"""
import importlib.util
import os
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
HOOK = Path(os.path.expanduser("~/.estate/guards/hooks/ticket-default"))


def _pattern() -> str:
    if not HOOK.exists():
        pytest.skip("BLIND: no ticket-default hook on this machine")
    m = re.search(r"^pat='(.+)'$", HOOK.read_text(), re.M)
    assert m, "ticket-default no longer declares pat='...'"
    return m.group(1)


def _tracked():
    spec = importlib.util.spec_from_file_location("tracked", HERE / "tracked.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_incident_crew13_the_guards_commit_subject_names_its_ticket():
    subject = _tracked().commit_message(["state/a.json", "state/b.json"]).splitlines()[0]
    assert re.search(_pattern(), subject, re.I), subject
    assert "2 load-bearing" in subject


def test_incident_crew13_the_old_subject_is_refused_by_the_same_pattern():
    old = "LAW 24: 3 load-bearing file(s) changed outside git"
    assert not re.search(_pattern(), old, re.I)
