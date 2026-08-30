"""crew#648 CP4 (founder 2026-08-30: "have the shipped the state mCp ingestion ticket for all agents at
session start" ... "you need to ingest the whole estate in structured format" ... "guard any actions,
tool calls ... which return information they already have"): nothing at session start read the estate
MCP. estate-state-relay.py now injects the whole document at SessionStart; policy/reply.rego refuses a
reply that calls the estate green over a red document; policy/hooks.rego refuses a tool call that
re-fetches a section the document holds. Rules: the relay is wired for every session, the server comes
from the harness config (no literal URL or bearer), the relay decides nothing, the Rego cases hold."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
RELAY = HERE / "estate-state-relay.py"


def test_relay_is_wired_at_session_start_for_every_session() -> None:
    cfg = json.loads((HERE / "settings/settings.json").read_text())
    cmds = [
        h["command"] for b in cfg["hooks"]["SessionStart"] for h in b.get("hooks", [])
    ]
    assert any("estate-state-relay.py SessionStart" in c for c in cmds)
    assert not any(
        "estate-state-guard" in c
        for k in cfg["hooks"]
        for b in cfg["hooks"][k]
        for h in b.get("hooks", [])
        for c in [h["command"]]
    )


def test_no_literal_server_or_bearer_and_no_decision_in_the_relay() -> None:
    src = RELAY.read_text()
    assert "mcp.mumchimp.com" not in src and not re.search(r"Bearer\s+\S{8,}", src)
    assert "mcpServers" in src, (
        "the endpoint comes from the harness's own MCP config (LAW 46)"
    )
    assert "sys.exit(2)" not in src and "return 2" not in src, (
        "the relay decides nothing; the refusals are Rego"
    )


def test_selftest_holds() -> None:
    out = subprocess.run(
        [sys.executable, str(RELAY), "--selftest"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_rego_cases_hold() -> None:
    out = subprocess.run(
        [
            "opa",
            "test",
            "--ignore",
            "fixtures",
            "--ignore",
            "*.json",
            str(HERE / "policy"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "estate-state-relay" in (HERE / "opa-hook.py").read_text(), (
        "opa-hook hands the cached document to the policies as input.estate"
    )
