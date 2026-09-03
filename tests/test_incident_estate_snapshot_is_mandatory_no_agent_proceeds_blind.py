"""Founder, 2026-09-03 04:1xZ, after a session reported a Kimi key dead with no estate document in
hand: "no agent can proceed without it, furthermore I need to know exactly what it contains". The
relay injected the document at SessionStart and printed BLIND when it could not, and every guard
read that as "nothing is green" and carried on. THE CLASS: a session working blind and reporting as
if it saw. Now opa-hook.py re-fetches once when the cache is missing, unavailable or older than
30 minutes, hands input.estate.blind to the policies when there is still no document, and
policy/hooks.rego refuses every tool call but the fetch while policy/reply.rego refuses every reply
but a BLOCKED: one. The adapter decides nothing; the refusals are Rego, proved both ways here.

Record: idp docs/founder/estate-snapshot-is-mandatory.md."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
HOOK = HERE / "opa-hook.py"


def _hook(home: pathlib.Path):
    """opa-hook.py loaded by path under a HOME that holds no ~/.claude.json, so the relay has no
    server to dial and the only outcome of a fetch is a recorded failure (no network in a test)."""
    os.environ["HOME"] = str(home)
    loader = importlib.machinery.SourceFileLoader("opa_hook_under_test", str(HOOK))
    mod = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(loader.name, loader)
    )
    loader.exec_module(mod)
    return mod


def _cache(home: pathlib.Path, minutes_old: float, **state) -> None:
    fetched = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - minutes_old * 60)
    )
    (home / ".estate").mkdir(parents=True, exist_ok=True)
    (home / ".estate" / "estate-state.json").write_text(
        json.dumps(
            {
                "fetched_at": fetched,
                "available": True,
                "stale": False,
                "document": {},
                **state,
            }
        )
    )


def test_no_cache_and_no_server_reads_blind_with_the_reason_and_backs_off(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    h = _hook(tmp_path)
    t0 = time.monotonic()
    snap = h.estate_snapshot()
    assert snap["blind"] is True and snap["fresh"] is False, snap
    assert ".claude.json" in snap["blind_reason"], (
        snap
    )  # no harness config under this HOME, so no server to dial
    marker = tmp_path / ".estate" / "estate-state.blind.json"
    assert marker.exists(), (
        "a failed fetch is remembered so the next refusal is instant"
    )
    again = h.estate_snapshot()
    assert again["blind_reason"] == snap["blind_reason"]
    assert time.monotonic() - t0 < 5, (
        "two blind readings must fit inside one hook budget"
    )


def test_a_fresh_cache_is_fresh_and_never_dials(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _cache(tmp_path, minutes_old=3)
    h = _hook(tmp_path)
    snap = h.estate_snapshot()
    assert snap["fresh"] is True and not snap.get("blind"), snap
    assert not (tmp_path / ".estate" / "estate-state.blind.json").exists()


def test_an_old_document_that_cannot_be_refreshed_is_kept_not_blind(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    _cache(tmp_path, minutes_old=45)
    h = _hook(tmp_path)
    snap = h.estate_snapshot()
    assert snap["fresh"] is False and not snap.get("blind"), snap
    assert snap["age_minutes"] >= 45, "the old document is handed over, not thrown away"


def test_an_unavailable_answer_is_blind(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _cache(
        tmp_path,
        minutes_old=1,
        available=False,
        reason="artifact estate-state not found",
    )
    h = _hook(tmp_path)
    snap = h.estate_snapshot()
    assert snap["blind"] is True, snap
    assert ".claude.json" in snap["blind_reason"], snap


def _run_hook(home: pathlib.Path, payload: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@pytest.mark.skipif(
    not any(
        os.access(os.path.join(p, "opa"), os.X_OK)
        for p in os.environ.get("PATH", "").split(os.pathsep)
    ),
    reason="opa not on PATH",
)
def test_the_hook_refuses_a_blind_session_and_allows_the_fetch(tmp_path):
    ls = _run_hook(
        tmp_path,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        },
    )
    assert ls.returncode == 2, ls.stdout + ls.stderr
    assert (
        "estate snapshot is mandatory" in ls.stderr
        and "estate-state-relay.py --fetch" in ls.stderr
    ), ls.stderr
    fetch = _run_hook(
        tmp_path,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 ~/.claude/scripts/estate-state-relay.py --fetch"
            },
        },
    )
    assert fetch.returncode == 0, fetch.stdout + fetch.stderr
    _cache(tmp_path, minutes_old=2)
    seeing = _run_hook(
        tmp_path,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        },
    )
    assert seeing.returncode == 0, seeing.stdout + seeing.stderr


@pytest.mark.skipif(
    not any(
        os.access(os.path.join(p, "opa"), os.X_OK)
        for p in os.environ.get("PATH", "").split(os.pathsep)
    ),
    reason="opa not on PATH",
)
def test_the_rego_cases_hold_both_ways() -> None:
    out = subprocess.run(
        [
            "opa",
            "test",
            *(
                str(HERE / "policy" / f)
                for f in (
                    "hooks.rego",
                    "hooks_test.rego",
                    "reply.rego",
                    "reply_test.rego",
                )
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_adapter_decides_nothing_about_blindness() -> None:
    src = HOOK.read_text()
    body = src[src.index("def estate_snapshot") : src.index("def refuse")]
    assert "return 2" not in body and "refuse(" not in body, (
        "the blind verdict is Rego's, the adapter only gathers"
    )
    for policy in ("hooks.rego", "reply.rego"):
        assert (
            'object.get(input, ["estate", "blind"], false) == true'
            in (HERE / "policy" / policy).read_text()
        )
