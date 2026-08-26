"""crew#280 / LAW 48: session 8f034e1e found the KINI worker down and wrote "I stop here since
you asked for a status ... say 'fix it' and I start". Rung 4, incident test through the real
Stop runner: opa-hook.py feeds the reply to policy/reply.rego, which carries the founder's
VIOLATION text; a fix report passes.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _stop(text: str, tmp_path: Path) -> str:
    t = tmp_path / "transcript.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
    payload = {"hook_event_name": "Stop", "transcript_path": str(t), "session_id": "test-crew280"}
    return subprocess.run([sys.executable, str(HERE / "opa-hook.py")], input=json.dumps(payload),
                          capture_output=True, text=True).stdout


def test_incident_crew280_pause_is_blocked_with_the_founders_words(tmp_path):
    out = _stop("INVENTORY: worker down.\nI stop here since you asked for a status; should I fix this?", tmp_path)
    assert "VIOLATION: Law of Continuous Execution. Do not ask to fix the bug. Fix it and report." in out
    assert json.loads(out)["decision"] == "block"


def test_incident_crew280_a_fix_report_passes(tmp_path):
    out = _stop("Found the KINI worker down. Fixed it in PR idp#151. Status is now green.\n"
                "STAGED: remove the old worktree. Reply 'hold' to cancel. Auto-activating in 60 minutes.\n"
                "\n---\n\nShould I fix this? (below the fold is free)", tmp_path)
    assert out.strip() == ""
