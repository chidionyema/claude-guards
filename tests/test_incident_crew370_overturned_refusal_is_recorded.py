"""crew#370, 2026-08-27: LAW 38 grades a guard by whether it refuses correct work, and nothing
recorded the one signal the estate has that a refusal was wrong: the agent appending an override
marker (`# raw-diff-intended`, `# main-is-red`, `# in-flight`) and the same hook then passing it.
`refused` was on the ledger since crew#391; the pass-with-marker was not, so false_refusals had
no writer.

Rule, both ways: a hook that passes a command carrying a marker writes `waived: <marker>` on its
row; a pass without a marker, and a refusal with one, write no `waived` key (a refused marker is
the guard holding, not being overturned).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RUN = HERE / "hook-run.py"
PASS_HOOK = "import sys; sys.stdin.read(); sys.exit(0)"
BLOCK_HOOK = "import sys; sys.stdin.read(); sys.exit(2)"


def _run(tmp_path: Path, body: str, command: str) -> dict:
    hook = tmp_path / "h.py"
    hook.write_text(body)
    ledger = tmp_path / "ledger.jsonl"
    payload = json.dumps({"hook_event_name": "PreToolUse", "session_id": "abcdef0123",
                          "tool_name": "Bash", "tool_input": {"command": command}})
    subprocess.run([sys.executable, str(RUN), str(hook)], input=payload, text=True,
                   capture_output=True, env={**os.environ, "HOOK_OUTCOMES": str(ledger)})
    return json.loads(ledger.read_text().splitlines()[-1])


def test_pass_with_marker_records_the_marker(tmp_path):
    row = _run(tmp_path, PASS_HOOK, "git diff a b  # raw-diff-intended")
    assert row["refused"] is False and row["waived"] == "raw-diff-intended"
    assert _run(tmp_path, PASS_HOOK, "gh pr merge 5 # main-is-red")["waived"] == "main-is-red"


def test_pass_without_marker_and_refused_with_marker_record_nothing(tmp_path):
    assert "waived" not in _run(tmp_path, PASS_HOOK, "git diff main...HEAD")
    row = _run(tmp_path, BLOCK_HOOK, "git push --force # force-push-intended")
    assert row["refused"] is True and "waived" not in row
