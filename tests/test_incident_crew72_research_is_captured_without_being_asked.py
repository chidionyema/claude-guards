"""crew#72: the research function had a writer nobody wired.

Rule: a WebSearch or WebFetch leaves a row on the session's research trail through
decision-log.py, without the session doing anything. The hook never blocks a tool.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "research-capture.py"


def _run(payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env={**os.environ, **env}, timeout=60)


def test_incident_crew72_search_and_fetch_land_on_one_row(tmp_path):
    env = {"DECISION_LOG": str(tmp_path / "D.jsonl"), "RESEARCH_CAPTURE_STATE": str(tmp_path / "st")}
    s = {"session_id": "abcdef12-0000", "tool_name": "WebSearch",
         "tool_input": {"query": "flux image automation never pushes"}, "tool_response": [1, 2, 3]}
    f = {"session_id": "abcdef12-0000", "tool_name": "WebFetch",
         "tool_input": {"url": "https://fluxcd.io/flux/components/image/", "prompt": "why no push"}}
    assert _run(s, env).returncode == 0
    assert _run(f, env).returncode == 0
    rows = [json.loads(x) for x in (tmp_path / "D.jsonl").read_text().splitlines()]
    latest = rows[-1]
    assert latest["kind"] == "research" and latest["question"] == "flux image automation never pushes"
    assert latest["searches"][0]["q"] == "flux image automation never pushes" and latest["searches"][0]["n_results"] == 3
    assert latest["sources"][0]["url"].startswith("https://fluxcd.io") and latest["sources"][0]["publisher"] == "fluxcd.io"
    assert len({r["id"] for r in rows}) == 1, "one research row per session, not one per call"


def test_incident_crew72_other_tools_and_bad_input_never_block(tmp_path):
    env = {"DECISION_LOG": str(tmp_path / "D.jsonl"), "RESEARCH_CAPTURE_STATE": str(tmp_path / "st")}
    assert _run({"tool_name": "Bash", "tool_input": {"command": "ls"}}, env).returncode == 0
    p = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True,
                       env={**os.environ, **env}, timeout=30)
    assert p.returncode == 0
    assert not (tmp_path / "D.jsonl").exists()


def test_incident_crew72_hook_is_wired_in_settings():
    s = json.loads((ROOT / "settings" / "settings.json").read_text())
    cmds = [h["command"] for m in s["hooks"].get("PostToolUse", []) for h in m["hooks"]]
    assert any("research-capture.py" in c for c in cmds)
    matchers = [m.get("matcher", "") for m in s["hooks"]["PostToolUse"]
                if any("research-capture.py" in h["command"] for h in m["hooks"])]
    assert matchers and all("WebSearch" in m and "WebFetch" in m for m in matchers)
