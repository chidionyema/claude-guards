"""Rung 4 (incident test). crew#407, 2026-08-27: a session sent the router console password to
the founder's Telegram; #113 closed the Telegram senders. The reply text and gh comment bodies
were the two remaining paths a value could take. credential-guard.py refuses both. Proved both
ways: a value is refused, the name of where a value lives passes. Fixtures are built at runtime
so no credential shape is ever committed (the compile grep and gitleaks scan this file)."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
HOOK = HERE / "credential-guard.py"
GHP = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True)


def _stop(text: str, tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    t = tmp_path / "transcript.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
    return _run({"hook_event_name": "Stop", "transcript_path": str(t), "session_id": "test-crew407"})


def _bash(cmd: str, cwd: pathlib.Path) -> subprocess.CompletedProcess:
    return _run({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)})


def test_a_reply_carrying_a_value_is_refused_and_the_value_is_not_echoed(tmp_path):
    r = _stop("The console login is admin and the " + "password: " + "hunter2Kx9!pq" + " for now.", tmp_path)
    assert r.returncode == 2 and "REFUSED" in r.stderr, r
    assert "hunter2" not in r.stderr and GHP not in r.stderr


def test_a_reply_naming_where_the_value_lives_passes(tmp_path):
    r = _stop("The console signs in through IDCS SSO; the break-glass value lives only in vault entry "
              "litellm-ui, never read out. Password rotated. SEED_LITELLM_UI_PASSWORD deleted.", tmp_path)
    assert r.returncode == 0, r.stderr


def test_a_gh_comment_body_with_a_token_is_refused(tmp_path):
    r = _bash(f'gh issue comment 407 -R chidionyema/crew --body "use token: {GHP} to read it"', tmp_path)
    assert r.returncode == 2 and "REFUSED" in r.stderr and GHP not in r.stderr, r


def test_a_gh_body_file_with_a_value_is_refused(tmp_path):
    (tmp_path / "body.md").write_text("## Evidence\n" + "client_secret: " + "Zq8v3mLp0xT2wR5y\n")
    r = _bash("gh pr create --title x --body-file body.md", tmp_path)
    assert r.returncode == 2 and "REFUSED" in r.stderr, r


def test_a_gh_comment_naming_the_vault_entry_passes_and_reads_are_never_judged(tmp_path):
    ok = _bash('gh issue comment 407 --body "client secret lives in vault secret oauth2-proxy-client-secret; rotated"', tmp_path)
    assert ok.returncode == 0, ok.stderr
    # a read that merely mentions a value elsewhere in the same command is not a publish
    view = _bash(f'gh pr view 283 --json body | grep -c {GHP}', tmp_path)
    assert view.returncode == 0, view.stderr
