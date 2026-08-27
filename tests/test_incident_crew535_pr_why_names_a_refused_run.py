"""Incident test, crew#535 CP3 (2026-08-27): pr-why.py prints WHY a run is red, not "(no log)".

On 2026-08-27 every job on a private repo failed with 0 steps and no log; the check-run
annotation said "The job was not started because recent account payments have failed or your
spending limit needs to be increased". `why()` returned "(no log: the run was cancelled, or the
log has expired)" and three sessions graded the red as a PR fault for ~3h. Rule: when the log
is empty, `why()` must look at the check-run annotations and name the refusal — and if the
refusal is billing, point the founder at https://github.com/settings/billing.
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(HERE, "pr-why.py")


def _pr_why():
    spec = importlib.util.spec_from_file_location("pr_why", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_gh(logs: str = "", annotations: str = ""):
    """A `gh` stand-in that returns different output for the logs vs annotations call."""
    def _gh(args):
        joined = " ".join(args)
        if "check-runs" in joined and "annotations" in joined:
            return annotations
        if "actions/jobs" in joined and "/logs" in joined:
            return logs
        return ""
    return _gh


BILLING_MSG = ("The job was not started because recent account payments have failed or "
               "your spending limit needs to be increased")


def test_incident_crew535_refused_run_is_named_and_the_founder_is_pointed_at_billing(monkeypatch):
    pr = _pr_why()
    monkeypatch.setattr(pr, "gh",
                        _fake_gh(logs="", annotations=json.dumps([{"message": BILLING_MSG}])))
    shown, causes = pr.why("owner/repo", "123", keep=6)
    assert any("refused before the first step" in ln for ln in shown), shown
    assert any("FOUNDER ACTION" in ln and "https://github.com/settings/billing" in ln for ln in shown), shown
    assert len(causes) == 1
    assert causes[0].startswith("refused: The job was not started")


def test_incident_crew535_no_log_and_no_annotation_keeps_the_extended_message(monkeypatch):
    pr = _pr_why()
    monkeypatch.setattr(pr, "gh", _fake_gh(logs="", annotations="[]"))
    shown, causes = pr.why("owner/repo", "123", keep=6)
    assert shown == ["(no log: the run was cancelled, refused before its first step, or the log has expired)"], shown
    assert causes == []


def test_incident_crew535_a_log_with_an_assertion_line_is_unaffected(monkeypatch):
    pr = _pr_why()
    log = "FAILED tests/test_foo.py::test_bar - assert None == 5\n"
    monkeypatch.setattr(pr, "gh", _fake_gh(logs=log, annotations="[]"))
    shown, causes = pr.why("owner/repo", "123", keep=6)
    assert any("FAILED tests/test_foo.py::test_bar" in ln for ln in shown), shown
    assert not any("refused" in ln for ln in shown), shown
    assert causes == ["tests/test_foo.py::test_bar"]
