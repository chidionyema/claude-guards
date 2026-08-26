"""Incident test (rung 4): crew#25: estate_watch called a 191-minute-old receipt stale; STALE window must match the 6 h audit.

Executes the scenario in features/hard_execution_chain.feature by running the
script's own selftest, which proves the rule both ways (one case that must fail,
one that must not).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_incident_crew25_stale_window():
    r = subprocess.run([sys.executable, os.path.join(HERE, "estate/estate_watch.py"), "--selftest"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
