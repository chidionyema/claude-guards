"""Incident test (rung 4): crew#307: estate_board.py claim exited 0 doing nothing; claim must post a CLAIM comment and unknown subcommands exit 2.

Executes the scenario in features/hard_execution_chain.feature by running the
script's own selftest, which proves the rule both ways (one case that must fail,
one that must not).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_incident_crew307_board_claim_cli():
    r = subprocess.run([sys.executable, os.path.join(HERE, "estate_board.py"), "--selftest"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
