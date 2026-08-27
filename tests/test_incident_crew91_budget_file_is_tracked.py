"""Incident test, crew#91 (2026-08-24): the estate's spend policy was one
untracked file on one laptop (LAW 24). Rule: the budget file is a tracked
path in this repo, and both levers parse as numbers, so a change to what the
estate may spend has a diff, an author and a date. Both ways: the tracked file
passes; a copy git does not hold fails the same check."""
import json
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKED = os.path.join("estate", "estate-budget.json")


def _is_tracked(rel):
    out = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO,
                         capture_output=True, text=True)
    return out.returncode == 0


def test_incident_crew91_budget_file_is_tracked_and_levers_parse():
    assert _is_tracked(TRACKED)
    d = json.load(open(os.path.join(REPO, TRACKED)))
    for lever in ("warn_usd", "halt_usd", "downshift_usd"):
        assert isinstance(d[lever], (int, float)), lever


def test_incident_crew91_an_untracked_copy_fails_the_same_check(tmp_path):
    assert not _is_tracked(os.path.join("estate", "estate-budget.untracked.json"))
