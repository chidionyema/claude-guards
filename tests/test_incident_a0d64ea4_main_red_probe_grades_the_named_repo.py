"""Incident, 2026-08-28 (session a0d64ea4): `gh pr merge 553 --repo chidionyema/crew --merge` run from
an idp worktree was refused with "main is red" — rule-guard's main-red probe ran `gh run list
--branch main` in the SESSION repo (idp, run 33191186332 red) while crew main was green at 0e51504.
`_pr_check_states` already honoured the merge's own `--repo`; the main-red probe and its job reader
did not. Now all three grade the repository the merge names.
"""
import importlib.util
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "rule-guard.py"
MERGE = "gh pr " + "merge"  # split so no shell hook reads this file as a merge command


def _load():
    spec = importlib.util.spec_from_file_location("rg", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(monkeypatch, mod):
    calls = []

    class _Proc:
        returncode = 0
        stdout = "failure\t1\tabc\n"

    def fake_run(argv, **kw):
        calls.append(list(argv))
        return _Proc()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return calls


def test_the_merge_repo_flag_is_read_from_the_merge_segment_only():
    mod = _load()
    assert mod._merge_repo_slug(f"{MERGE} 553 --repo chidionyema/crew --merge") == "chidionyema/crew"
    assert mod._merge_repo_slug(f"{MERGE} 553 -R chidionyema/crew") == "chidionyema/crew"
    assert mod._merge_repo_slug(f"{MERGE} 553 --merge") is None
    assert mod._merge_repo_slug(f"gh pr view 1 --repo other/x && {MERGE} 553 --merge") is None


def test_main_red_probe_asks_the_named_repo_not_the_session_repo(monkeypatch):
    mod = _load()
    calls = _capture(monkeypatch, mod)
    mod._main_red_refusal("chidionyema/crew")
    run_list = [c for c in calls if c[1:3] == ["run", "list"]]
    assert run_list and run_list[0][-2:] == ["--repo", "chidionyema/crew"]
    jobs = [c for c in calls if c[1] == "api"]
    assert jobs and jobs[0][2].startswith("repos/chidionyema/crew/actions/runs/1/jobs")


def test_without_a_repo_flag_the_probe_grades_the_session_repo(monkeypatch):
    mod = _load()
    calls = _capture(monkeypatch, mod)
    mod._main_red_refusal(None)
    run_list = [c for c in calls if c[1:3] == ["run", "list"]]
    assert run_list and "--repo" not in run_list[0]
    jobs = [c for c in calls if c[1] == "api"]
    assert jobs and jobs[0][2].startswith("repos/{owner}/{repo}/actions/runs/1/jobs")
