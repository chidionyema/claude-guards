"""crew#603 (founder, 2026-08-28: "If a guard crashes, the answer is 'no'"). Two ways the door
stood open. (1) hook-run.py handed a crashed, missing or hung guard's exit code straight to
Claude Code, which reads anything but 2 as a warning, so the action went ahead. (2)
vendor-lock-guard and jargon-guard switched themselves off after three refusals in a session and
passed a repeated text on the second try. Rules: every way a guard fails to reach a verdict is
exit 2 with a block decision and a ledger row refused=true; the fourth refusal is the first.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RUN = HERE / "hook-run.py"
JARGON = HERE / "jargon-guard.py"
VENDOR = HERE / "vendor-lock-guard.py"

CRASH = "import sys; sys.stdin.read(); raise RuntimeError('the ledger is on fire')"
HANG = "import sys, time; sys.stdin.read(); time.sleep(30)"
WRONG_EXIT = "import sys; sys.stdin.read(); sys.exit(1)"


def _run(tmp_path: Path, body: str | None, name: str, **env):
    hook = tmp_path / name
    if body is not None:
        hook.write_text(body)
    ledger = tmp_path / "hook-outcomes.jsonl"
    payload = json.dumps({"hook_event_name": "PreToolUse", "session_id": "abcdef0123",
                          "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    proc = subprocess.run([sys.executable, str(RUN), str(hook)], input=payload, text=True,
                          capture_output=True,
                          env={**os.environ, "HOOK_OUTCOMES": str(ledger), **env})
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    return proc, rows


def _refused(proc, rows, why: str):
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    out = json.loads(proc.stdout)
    assert out["decision"] == "block"
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "fail-closed" in out["reason"] and why in out["reason"], out["reason"]
    assert rows and rows[-1]["refused"] is True and rows[-1]["exit"] == 2


def test_a_guard_that_raises_is_a_refusal_naming_the_crash(tmp_path):
    _refused(*_run(tmp_path, CRASH, "crash.py"), "the ledger is on fire")


def test_a_guard_that_exits_one_is_a_refusal_not_a_warning(tmp_path):
    _refused(*_run(tmp_path, WRONG_EXIT, "one.py"), "exit 1")


def test_a_missing_guard_is_a_refusal(tmp_path):
    _refused(*_run(tmp_path, None, "gone.py"), "no such file")


def test_a_guard_that_hangs_is_a_refusal(tmp_path):
    _refused(*_run(tmp_path, HANG, "hang.py", HOOK_TIMEOUT="1"), "no verdict inside 1s")


def test_a_passing_guard_still_passes(tmp_path):
    proc, rows = _run(tmp_path, "import sys; sys.stdin.read(); sys.exit(0)", "ok.py")
    assert proc.returncode == 0 and rows[-1]["refused"] is False


def _transcript(tmp_path: Path, text: str) -> Path:
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
                             "content": [{"type": "text", "text": text}]}}) + "\n")
    return t


def _stop(guard: Path, tmp_path: Path, text: str, home: Path):
    payload = json.dumps({"hook_event_name": "Stop", "session_id": "wear-me-down",
                          "transcript_path": str(_transcript(tmp_path, text))})
    return subprocess.run([sys.executable, str(guard)], input=payload, text=True,
                          capture_output=True, env={**os.environ, "HOME": str(home)})


def test_jargon_guard_refuses_the_same_text_a_fifth_time(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    text = "The client-bundled bearer token needs a hotfix in the idempotent orchestrator."
    codes = [_stop(JARGON, tmp_path, text, home).returncode for _ in range(5)]
    assert codes == [2, 2, 2, 2, 2], codes


def test_vendor_lock_guard_refuses_the_same_text_a_fifth_time(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    text = ("## Phone path\n\nStep 1: in Claude Code run `/config` and turn on Remote Control "
            "for all sessions. Only you can do it.\n")
    outs = [_stop(VENDOR, tmp_path, text, home).stdout for _ in range(5)]
    decisions = [json.loads(o)["decision"] if o.strip() else "pass" for o in outs]
    assert decisions == ["block"] * 5, decisions


OPA_HOOK = HERE / "opa-hook.py"


def _opa(payload: dict, **env):
    return subprocess.run([sys.executable, str(OPA_HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env={**os.environ, **env})


def test_opa_hook_with_no_opa_on_path_refuses_instead_of_passing(tmp_path):
    # PATH holding only an empty dir: shutil.which("opa") finds nothing.
    empty = tmp_path / "bin"
    empty.mkdir()
    proc = _opa({"hook_event_name": "PreToolUse", "tool_name": "Write",
                 "tool_input": {"file_path": "/x/README.md", "content": ""}}, PATH=str(empty))
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "no `opa` on PATH" in out["reason"] and "fail-closed" in out["reason"]


def test_opa_hook_unreadable_payload_refuses():
    proc = subprocess.run([sys.executable, str(OPA_HOOK)], input="not json", text=True, capture_output=True)
    assert proc.returncode == 2 and "payload is not JSON" in json.loads(proc.stdout)["reason"]


def test_opa_hook_refuses_a_rogue_markdown_and_allows_an_explanation_doc():
    import shutil
    if not shutil.which("opa"):
        import pytest
        pytest.skip("opa not installed here; the rego suite covers the rule")
    rogue = _opa({"hook_event_name": "PreToolUse", "tool_name": "Write",
                  "tool_input": {"file_path": "/Users/x/dev/code/idp/RESEARCH.md", "content": "# r"}})
    assert rogue.returncode == 2 and "ADR 0002" in rogue.stderr
    fine = _opa({"hook_event_name": "PreToolUse", "tool_name": "Write",
                 "tool_input": {"file_path": "/Users/x/dev/code/idp/docs/explanation/r.md", "content": "# r"}})
    assert fine.returncode == 0, fine.stderr


def test_every_write_edit_and_bash_call_reaches_the_door():
    """The rule is data; it only bites if settings wires opa-hook onto the events it judges."""
    s = json.loads((HERE / "settings" / "settings.json").read_text())
    wired = {g["matcher"] for g in s["hooks"]["PreToolUse"]
             if any("opa-hook.py" in h["command"] for h in g["hooks"])}
    assert {"Write|Edit", "Bash", "Artifact"} <= wired, wired
