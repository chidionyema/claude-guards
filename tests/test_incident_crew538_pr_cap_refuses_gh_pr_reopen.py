"""Incident test, crew#538: 25 closed PRs were reopened for rescue in one sweep on 2026-08-27 and
the queue sat at the cap for hours ("we gonna hit the cap again and slow down, unsustainable").

`gh pr reopen` takes a slot exactly as `gh pr create` does, so it is refused past the cap and
allowed at it. Cases pin PR_CAP=10 like the crew#504 test.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_incident_crew504_pr_cap_refuses_gh_pr_create import _env_with_fake_gh, _run  # noqa: E402


def test_reopen_past_the_cap_is_refused(tmp_path):
    r = _run("gh pr reopen 7 -R o/r", _env_with_fake_gh(tmp_path, 11))
    assert r.returncode == 2, r.stderr
    assert "BLOCKED by pr-cap-guard" in r.stderr


def test_reopen_at_the_cap_is_allowed(tmp_path):
    r = _run("gh pr reopen 7 -R o/r", _env_with_fake_gh(tmp_path, 10))
    assert r.returncode == 0, r.stderr
