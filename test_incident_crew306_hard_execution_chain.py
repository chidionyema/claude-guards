"""Rung 4 (incident test): crew#306. Founder, 2026-08-26: agents ended turns goalless, claimed
"nothing independent" with runs in flight, and sat idle for 10+ minutes. Each script's
selftest holds the refuse and the permit case; this makes CI run them as one test.
crew#638 removed the auto-objective row: the founder's triage deleted that script for judging
whether a session was idle, a thing no file records."""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _selftest(name: str) -> None:
    r = subprocess.run([sys.executable, str(HERE / name), "--selftest"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "FAIL" not in r.stdout, f"{name}\n{r.stdout}\n{r.stderr}"


def test_incident_crew306_session_timeout():
    _selftest("session-timeout.py")


def test_incident_crew306_board():
    _selftest("estate_board.py")


if __name__ == "__main__":
    for f in (test_incident_crew306_session_timeout, test_incident_crew306_board):
        f(); print("PASS", f.__name__)
