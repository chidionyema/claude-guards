"""Incident test (rung 4): crew#306 CP3, 2026-08-27: session-timeout's first enforce hits were
`FAILED kill 9f8f4f5f pid 72761: [Errno 3] No such process` and later `pid 8338` for the same
session -- lsof named a transient reader that was gone by kill time; the claim stayed held and
no ledger row was written. Rule: a pid gone before the kill re-resolves the holder; an unheld
transcript is ENDED and released; every other kill failure is a `kill_failed` ledger row.

Executes the scenario by running the script's own selftest, which proves the rule both ways
(the ENDED case and the FAILED case are asserted by name below).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_incident_crew306_timeout_reaps_a_dead_pid():
    r = subprocess.run([sys.executable, os.path.join(HERE, "session-timeout.py"), "--selftest"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS a pid that vanished before the kill is ENDED" in r.stdout, r.stdout
    assert "PASS any other kill failure is FAILED and on the ledger" in r.stdout, r.stdout
