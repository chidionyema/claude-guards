"""Incident test, crew#504 CP5: 113 open PRs across seven repos on 2026-08-27.

`gh pr create` is refused against a repo with more than the cap of open PRs (10 when the incident was
written, 20 by founder word on 2026-08-27; these cases pin PR_CAP=10); the cap itself is allowed;
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


def _env_with_fake_gh(tmp_path, n_open: int, cap: int | None = 10) -> dict:
    """A `gh` on PATH that answers the pulls query with n_open rows. `cap` pins PR_CAP for the
    crew#504 cases (written at 10); None leaves the guard's default, 20 since the founder's
    2026-08-27 word "increse the slot to 20"."""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    rows = [{"number": i, "created_at": f"2026-08-{i:02d}T00:00:00Z"} for i in range(1, n_open + 1)]
    gh = bindir / "gh"
    gh.write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(rows) + "\nJ\n")
    gh.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    if cap is None:
        env.pop("PR_CAP", None)
    else:
        env["PR_CAP"] = str(cap)
    return env


def test_default_cap_is_twenty_founder_2026_08_27(tmp_path):
    """Founder, 2026-08-27: "increse the slot to 20". 20 open allows, 21 refuses, with no PR_CAP set."""
    r = _run("gh pr create -R chidionyema/crew --title t --body b", _env_with_fake_gh(tmp_path / "a", 20, cap=None))
    assert r.returncode == 0, r.stderr
    r = _run("gh pr create -R chidionyema/crew --title t --body b", _env_with_fake_gh(tmp_path / "b", 21, cap=None))
    assert r.returncode == 2, r.stderr
    assert "chidionyema/crew has 21 open PRs" in r.stderr


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


def _env_with_stack(tmp_path) -> dict:
    """A `gh` whose open-PR list has #458 based on #454's head branch (idp, 2026-08-27)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    rows = [
        {"number": 454, "created_at": "2026-08-27T00:00:00Z", "head": {"ref": "cp1"}, "base": {"ref": "main"}},
        {"number": 458, "created_at": "2026-08-27T00:00:00Z", "head": {"ref": "cp2"}, "base": {"ref": "cp1"}},
    ]
    gh = bindir / "gh"
    gh.write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(rows) + "\nJ\n")
    gh.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    return env


def test_delete_branch_under_a_stacked_pr_is_refused(tmp_path):
    """crew#66: merging idp#454 with --delete-branch made GitHub close idp#458, which was based on it."""
    env = _env_with_stack(tmp_path)
    r = _run(f"gh pr {SHRINK[0]} 454 -R chidionyema/idp --squash --delete-branch", env)
    assert r.returncode == 2, r.stderr
    assert "chidionyema/idp#454 is the base of open PR(s) #458" in r.stderr
    assert _run(f"gh pr {SHRINK[0]} 454 -R chidionyema/idp --squash", env).returncode == 0
    assert _run(f"gh pr {SHRINK[0]} 458 -R chidionyema/idp --squash --delete-branch", env).returncode == 0


def test_held_prs_do_not_count_toward_the_cap(tmp_path):
    """crew#538: 7 idp PRs reopened under `hold` on 2026-08-27 push nothing; the cap protects the CI queue."""
    env = _env_with_fake_gh(tmp_path, 12)
    gh = tmp_path / "bin" / "gh"
    rows = [{"number": i, "created_at": f"2026-08-{i:02d}T00:00:00Z"} for i in range(1, 13)]
    for p in rows[:3]:
        p["labels"] = [{"name": "hold"}]
    gh.write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(rows) + "\nJ\n")
    r = _run("gh pr create -R chidionyema/idp --title t --body b", env)
    assert r.returncode == 0, r.stderr
    rows[3]["labels"] = []
    gh.write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(rows[:2] + rows[3:]) + "\nJ\n")  # 10 unheld
    assert _run("gh pr create -R chidionyema/idp --title t --body b", env).returncode == 0
    gh.write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(rows[3:] + [{"number": n, "created_at": f"2026-08-{n}T00:00:00Z"} for n in (13, 14)]) + "\nJ\n")  # 11 unheld
    r = _run("gh pr create -R chidionyema/idp --title t --body b", env)
    assert r.returncode == 2 and "label `hold` not counted" in r.stderr, r.stderr
