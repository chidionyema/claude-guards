"""Incident test (rung 4), crew#51: rule-guard read `echo "do not run git push"` as a push.

Executes the scenario in features/hard_execution_chain.feature through rule-guard's own
selftest, which holds the permit case (echo/printf payload) and the refuse case (the
command chained after the echo).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_incident_crew51_echo_payload():
    r = subprocess.run([sys.executable, os.path.join(HERE, "rule-guard.py"), "--selftest"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "crew#51" not in r.stdout or "FAIL" not in r.stdout
