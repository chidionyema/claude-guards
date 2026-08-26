"""Rung 4 (incident test). 2026-08-26, session 78caaa17: `git push -q ... | tail -1`
printed nothing when the pre-push hook refused, and the reply reported the commit
as pushed. Rule quiet_push in policy/command.rego. Proved both ways."""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rule_guard", HERE / "rule-guard.py")
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)


def _verdict(cmd: str):
    return rg.decide(cmd)


def test_incident_quiet_push_is_refused():
    for cmd in ("git push -q origin main", "git push --quiet 2>&1 | tail -1", "cd x && git push -q -u origin b"):
        assert _verdict(cmd) is not None, cmd


def test_incident_loud_push_and_marker_pass():
    for cmd in ("git push origin HEAD 2>&1 | tail -3", "git push -q origin feat/x  # quiet-push-intended", "git commit -q -m x"):
        assert _verdict(cmd) is None, cmd
