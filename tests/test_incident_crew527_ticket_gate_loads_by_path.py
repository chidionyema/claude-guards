"""crew#527 CP4 incident, 2026-08-28T01:05Z: ai.aiden.watch failed every tick with
``ModuleNotFoundError: No module named 'issue_dod'`` and the scheduler breaker opened.
ticket-gate.py gained ``from issue_dod import ...`` (5c535df); that works when the file runs
as a script (its directory is sys.path[0]) and breaks when aiden/tick.py loads it by path
with importlib, where its directory is not on sys.path at all.

Rule: ticket-gate.py is importable by path from any working directory with a clean sys.path.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def test_ticket_gate_imports_by_path_from_a_foreign_cwd(tmp_path):
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('ticket_gate', {str(HERE / 'ticket-gate.py')!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "print('loaded', callable(getattr(m, 'issue_body', None)))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    assert "loaded True" in r.stdout
