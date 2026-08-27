"""crew#423 rows 16 and 25 (claude-guards#137 review): the checkpoint-age adapters in opa-hook.py
and rule-guard.py graded two shapes as stale that are not: a subagent transcript, whose parent
directory is `subagents` and holds no checkpoints/, and a project that has never written LATEST.md.
Both returned 10**9, a verdict, and every `git worktree add` from a subagent was refused. Rule: the
adapter returns None (BLIND, no verdict) unless it measured a real file, and a subagent's project is
two levels above its transcript. Rung 4, both ways, both adapters in one run."""
import importlib.util
import os
import pathlib
import time

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("script", ["opa-hook.py", "rule-guard.py"])
def test_age_is_measured_for_a_session_and_a_subagent_and_blind_otherwise(tmp_path, script):
    age = _load(script).checkpoint_age_s
    project = tmp_path / "proj"
    session = project / "sess"
    (session / "subagents").mkdir(parents=True)
    (session / "subagents" / "agent-1.jsonl").write_text("")
    (session / "t.jsonl").write_text("")
    # never checkpointed: blind, not stale
    assert age(str(session / "t.jsonl")) is None
    assert age(None) is None
    (project / "checkpoints").mkdir()
    latest = project / "checkpoints" / "LATEST.md"
    latest.write_text("# RESUME HERE")
    os.utime(latest, (time.time() - 7200, time.time() - 7200))
    # the session transcript and the subagent transcript measure the same file
    assert 7100 < age(str(project / "t.jsonl")) < 7300
    assert 7100 < age(str(session / "subagents" / "agent-1.jsonl")) < 7300
