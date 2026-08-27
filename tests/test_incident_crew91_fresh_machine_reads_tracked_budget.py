"""Incident test, crew#91 half 2 (2026-08-27): a fresh machine has no
``~/.claude/estate-budget.json``, and before this every reader named that path
as a literal and fell over (LAW 27: setup needs you once, then never; LAW 46:
no file names where the home directory lives). Rule: readers resolve the path
through ``estate.budget_path.budget_path``, which prefers the machine-local
file when it exists and reads the tracked one otherwise. Both ways: with the
local file present it wins; with it absent the tracked file is returned and
parses. A final check refuses the old literal returning to any reader."""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "estate"))
from budget_path import budget_path, TRACKED  # noqa: E402

READERS = ["statusline-context.py", "estate/estate_downshift.py",
           "estate/estate_cost_sentinel.py", "founder_board.py"]


def test_incident_crew91_local_file_wins_when_present(tmp_path):
    local = tmp_path / "estate-budget.json"
    local.write_text("{}")
    assert budget_path(local=str(local), tracked="/nowhere") == str(local)


def test_incident_crew91_fresh_machine_reads_the_tracked_file(tmp_path):
    missing = str(tmp_path / "absent.json")
    got = budget_path(local=missing)
    assert got == TRACKED
    d = json.load(open(got))
    assert isinstance(d["warn_usd"], (int, float))


def test_incident_crew91_no_reader_names_the_home_path_as_a_literal():
    bad = re.compile(r'estate-budget\.json"\)')
    for rel in READERS:
        src = open(os.path.join(REPO, rel)).read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        assert not bad.search(code), rel
