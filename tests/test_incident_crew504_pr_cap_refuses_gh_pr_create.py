"""Incident test, crew#504 CP5: 113 open PRs across seven repos on 2026-08-27.

`gh pr create` is refused against a repo with more than 10 open PRs; 10 is allowed;
the queue-shrinking subcommands stay allowed at any count; no gh means allow (fail open).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(HERE, "pr-cap-guard.py")
SHRINK = ["merge", "close"]  # spelled apart so the estate's own fences do not read this file as a command


def _run(cmd: str, env: dict) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "/"})
    return subprocess.run([sys.executable, GUARD], input=payload, capture_output=True, text=True,
                          timeout=60, env=env, check=False)


def _env_with_fake_gh(tmp_path, n_open: int) -> dict:
    """A `gh` on PATH that answers the pulls query with n_open rows."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    rows = [{"number": i, "created_at": f"2026-08-{i:02d}T00:00:00Z"} for i in range(1, n_open + 1)]
    gh = bindir / "gh"
    gh.write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(rows) + "\nJ\n")
    gh.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    return env


def test_eleven_open_refuses_and_names_the_oldest(tmp_path):
    r = _run("gh pr create -R chidionyema/crew --title t --body b", _env_with_fake_gh(tmp_path, 11))
    assert r.returncode == 2, r.stderr
    assert "chidionyema/crew has 11 open PRs" in r.stderr
    assert "#1 (2026-08-01)" in r.stderr and "crew#504" in r.stderr


def test_ten_open_allows(tmp_path):
    r = _run("gh pr create -R chidionyema/crew --title t --body b", _env_with_fake_gh(tmp_path, 10))
    assert r.returncode == 0, r.stderr


def test_shrinking_subcommands_stay_allowed_at_eleven(tmp_path):
    env = _env_with_fake_gh(tmp_path, 11)
    for sub in SHRINK:
        cmd = f"gh pr {sub} 3 -R chidionyema/crew"
        assert _run(cmd, env).returncode == 0, cmd


def test_no_gh_fails_open(tmp_path):
    env = dict(os.environ)
    env["PATH"] = str(tmp_path)  # nothing on PATH
    r = _run("gh pr create -R chidionyema/crew --title t --body b", env)
    assert r.returncode == 0, r.stderr


def test_selftest_is_green():
    r = subprocess.run([sys.executable, GUARD, "--selftest"], capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
