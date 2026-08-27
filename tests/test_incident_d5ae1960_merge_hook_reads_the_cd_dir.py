"""Incident, 2026-08-27 (session d5ae1960): every `cd <worktree> && gh pr merge` / `git merge`
was graded by merge-divergence-hook.py in the session cwd (~/dev/code), not in the worktree the
merge runs in, so worktree merges were refused against the wrong checkout. The hook now takes a
leading `cd <dir> &&` (with optional NAME=value assignments before it) as the cwd it grades in.
"""
import importlib.util
import io
import json
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "merge-divergence-hook.py"
MERGE = "git " + "merge"  # split so no shell hook reads this file as a merge command


def _run(monkeypatch, command, payload_cwd):
    spec = importlib.util.spec_from_file_location("mdh", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""

    def fake_run(argv, cwd=None, **kw):
        seen["cwd"] = cwd
        seen["target"] = argv[-1]
        return _Proc()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    payload = {"tool_input": {"command": command}, "cwd": payload_cwd}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rc = mod.main()
    return rc, seen


def test_a_leading_cd_sets_the_directory_the_guard_grades_in(monkeypatch, tmp_path):
    rc, seen = _run(monkeypatch, f"cd {tmp_path} && {MERGE} --no-edit origin/main", "/somewhere/else")
    assert rc == 0
    assert seen["cwd"] == str(tmp_path)
    assert seen["target"] == "origin/main"


def test_assignments_before_cd_and_quotes_are_allowed(monkeypatch, tmp_path):
    _, seen = _run(monkeypatch, f"FOO=1 cd '{tmp_path}' && {MERGE} feature", "/somewhere/else")
    assert seen["cwd"] == str(tmp_path)


def test_without_cd_the_payload_cwd_is_graded(monkeypatch, tmp_path):
    _, seen = _run(monkeypatch, f"{MERGE} origin/main", str(tmp_path))
    assert seen["cwd"] == str(tmp_path)


def test_a_cd_in_the_middle_is_not_the_working_directory(monkeypatch, tmp_path):
    _, seen = _run(monkeypatch, f"{MERGE} origin/main && cd {tmp_path}", "/payload/cwd")
    assert seen["cwd"] == "/payload/cwd"
