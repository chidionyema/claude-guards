"""Incident test (rung 4), crew#23, 2026-08-26: the old escalate loop fired 18 times and delivered
0, and nothing said so. auto-objective's red-alert page had the same shape: the send result was
dropped and exceptions were swallowed. A page now prints PAGED crew#N or UNDELIVERED crew#N <why>.
Both ways run inside the script's own selftest; this test pins the two verdict lines."""
import subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "auto-objective.py"


def test_incident_crew23_page_receipt_both_ways() -> None:
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert "PASS scan names an undelivered page" in out, out
    assert "PASS scan prints a receipt for a delivered page" in out, out
    assert r.returncode == 0, out
