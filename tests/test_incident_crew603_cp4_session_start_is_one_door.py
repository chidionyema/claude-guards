"""crew#603 CP4, SessionStart batch. Founder, 2026-08-28: "Build ONE door (OPA). Every single
action the agent takes must pass through hooks.rego ... archive instead of delete, ensure they
cannot be reactivated."

Before: settings/settings.json named seven Python files on SessionStart, one hook each, and
which of them ran was a fact about a JSON file no policy could see. After: SessionStart is
one command (opa-hook.py); the list is `data.adapters.session_start`; each adapter runs
through hook-run.py so a crash refuses the start; and hooks.rego refuses any Bash or
settings.json edit that names scripts/archive/.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
OPA_HOOK = HERE / "opa-hook.py"


def run(policy_dir: Path, payload: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, "OPA_HOOK_POLICY": str(policy_dir), "HOOK_OUTCOMES": str(policy_dir / "ledger.jsonl")}
    return subprocess.run([sys.executable, str(OPA_HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, timeout=60)


def policy_with(tmp: Path, rows: list[list[str]], event: str = "session_start") -> Path:
    pol = tmp / "policy"
    pol.mkdir()
    (pol / "adapters.rego").write_text(
        f"package adapters\nimport rego.v1\n{event} := " + json.dumps(rows) + "\n")
    (pol / "hooks.rego").write_text("package hooks\nimport rego.v1\ndeny contains msg if { false; msg := \"\" }\n")
    return pol


def adapter(name: str, body: str) -> None:
    (HERE / name).write_text(textwrap.dedent(body))


def test_settings_session_start_is_exactly_one_command_and_it_is_opa_hook():
    hooks = json.loads((HERE / "settings" / "settings.json").read_text())["hooks"]["SessionStart"]
    cmds = [h["command"] for g in hooks for h in g["hooks"]]
    assert len(cmds) == 1, cmds
    assert cmds[0].endswith("hook-run.py $HOME/.claude/scripts/opa-hook.py"), cmds[0]


def test_settings_user_prompt_submit_is_exactly_one_command_and_it_is_opa_hook():
    hooks = json.loads((HERE / "settings" / "settings.json").read_text())["hooks"]["UserPromptSubmit"]
    cmds = [h["command"] for g in hooks for h in g["hooks"]]
    assert len(cmds) == 1 and cmds[0].endswith("hook-run.py $HOME/.claude/scripts/opa-hook.py"), cmds


def test_the_user_prompt_submit_list_names_the_five_adapters_settings_used_to_name():
    out = subprocess.run(["opa", "eval", "--format", "json", "--data", str(HERE / "policy" / "adapters.rego"),
                          "data.adapters.user_prompt_submit"], capture_output=True, text=True, timeout=30)
    rows = json.loads(out.stdout)["result"][0]["expressions"][0]["value"]
    assert [r[0] for r in rows] == ["directive-capture.py", "context-guard-hook.py", "goal-guard.py",
                                    "board-deliver.py", "feed-guard.py"]
    for r in rows:
        assert (HERE / r[0]).is_file(), f"{r[0]} is listed but not in the tree"


def test_a_user_prompt_submit_adapter_runs_through_the_same_door(tmp_path):
    adapter("zz-test-adapter-u.py", "print('UPS context')\n")
    try:
        pol = policy_with(tmp_path, [["zz-test-adapter-u.py"]], event="user_prompt_submit")
        p = run(pol, {"hook_event_name": "UserPromptSubmit", "session_id": "t5", "prompt": "hi"})
        assert p.returncode == 0, p.stderr
        out = json.loads(p.stdout)["hookSpecificOutput"]
        assert out["hookEventName"] == "UserPromptSubmit" and out["additionalContext"] == "UPS context"
    finally:
        (HERE / "zz-test-adapter-u.py").unlink(missing_ok=True)


def test_the_policy_list_names_the_seven_adapters_settings_used_to_name():
    out = subprocess.run(["opa", "eval", "--format", "json", "--data", str(HERE / "policy" / "adapters.rego"),
                          "data.adapters.session_start"], capture_output=True, text=True, timeout=30)
    rows = json.loads(out.stdout)["result"][0]["expressions"][0]["value"]
    assert [r[0] for r in rows] == ["laws-link-guard.py", "peer-loop-fence.py", "goal-guard.py", "memory-loop.py",
                                    "canonical-root-guard.py", "friction-relay.py", "feed-guard.py"]
    for r in rows:
        assert (HERE / r[0]).is_file(), f"{r[0]} is listed but not in the tree"


def test_adapter_context_is_joined_into_one_additional_context(tmp_path):
    adapter("zz-test-adapter-a.py", """\
        import json; print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "ALPHA"}}))
        """)
    adapter("zz-test-adapter-b.py", "print('BETA plain text')\n")
    try:
        pol = policy_with(tmp_path, [["zz-test-adapter-a.py"], ["zz-test-adapter-b.py"]])
        p = run(pol, {"hook_event_name": "SessionStart", "session_id": "t1"})
        assert p.returncode == 0, p.stderr
        ctx = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        assert ctx == "ALPHA\n\nBETA plain text", ctx
    finally:
        for n in ("zz-test-adapter-a.py", "zz-test-adapter-b.py"):
            (HERE / n).unlink(missing_ok=True)


def test_a_crashing_adapter_refuses_the_session_start_fail_closed(tmp_path):
    adapter("zz-test-adapter-crash.py", "raise RuntimeError('boom')\n")
    try:
        pol = policy_with(tmp_path, [["zz-test-adapter-crash.py"]])
        p = run(pol, {"hook_event_name": "SessionStart", "session_id": "t2"})
        assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
        assert "fail-closed" in p.stderr and "zz-test-adapter-crash.py" in p.stderr, p.stderr
    finally:
        (HERE / "zz-test-adapter-crash.py").unlink(missing_ok=True)


def test_a_missing_adapter_refuses_the_session_start(tmp_path):
    pol = policy_with(tmp_path, [["zz-no-such-adapter.py"]])
    p = run(pol, {"hook_event_name": "SessionStart", "session_id": "t3"})
    assert p.returncode == 2 and "zz-no-such-adapter.py" in p.stderr, p.stderr


def test_an_archived_name_in_the_list_never_runs(tmp_path):
    pol = policy_with(tmp_path, [["archive/scope-guard.py"]])
    p = run(pol, {"hook_event_name": "SessionStart", "session_id": "t4"})
    assert p.returncode == 2 and "archived" in p.stderr, p.stderr


def test_hooks_rego_refuses_reviving_the_archive_and_allows_reading_it():
    def deny(payload):
        out = subprocess.run(["opa", "eval", "--format", "json", "--ignore", "fixtures", "--ignore", "*.json",
                              "--data", str(HERE / "policy"), "--stdin-input", "data.hooks.deny"],
                             input=json.dumps(payload), capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout)["result"][0]["expressions"][0]["value"]
    assert deny({"tool_name": "Bash", "tool_input": {"command": "python3 ~/.claude/scripts/archive/scope-guard.py"}})
    assert deny({"tool_name": "Edit", "tool_input": {"file_path": "/x/.claude/scripts/settings/settings.json",
                                                      "old_string": "a", "new_string": "$HOME/.claude/scripts/archive/x.py"}})
    assert not deny({"tool_name": "Bash", "tool_input": {"command": "git log -3 -- scripts/archive/; cat scripts/archive/README.md"}})
