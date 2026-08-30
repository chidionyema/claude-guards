"""crew#648 CP4 (founder 2026-08-30: "have the shipped the state mCp ingestion ticket for all agents at
session start"): nothing at session start read the estate MCP. estate-state-guard.py now calls
get_estate_state at SessionStart and prints the red rows; at Stop it refuses a reply that calls the
estate green while a fresh document says red. Rules: the hook is wired for every session, the server
comes from the harness config (no literal URL or bearer), the selftest holds, and a reachable server
answers within the hook budget."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
HOOK = HERE / "estate-state-guard.py"


def test_hook_is_wired_at_session_start_and_stop_for_every_session() -> None:
    cfg = json.loads((pathlib.Path.home() / ".claude/settings.json").read_text())
    cmds = {
        k: [h["command"] for b in v for h in b.get("hooks", [])]
        for k, v in cfg["hooks"].items()
    }
    assert any("estate-state-guard.py SessionStart" in c for c in cmds["SessionStart"])
    assert any("estate-state-guard.py Stop" in c for c in cmds["Stop"])


def test_no_literal_server_or_bearer_in_the_hook() -> None:
    src = HOOK.read_text()
    assert "mcp.mumchimp.com" not in src and not re.search(r"Bearer\s+\S{8,}", src)
    assert "mcpServers" in src, (
        "the endpoint comes from the harness's own MCP config (LAW 46)"
    )


def test_selftest_holds() -> None:
    out = subprocess.run(
        [sys.executable, str(HOOK), "--selftest"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_a_missing_document_is_blind_never_quiet() -> None:
    ns: dict = {}
    exec(compile(HOOK.read_text(), str(HOOK), "exec"), ns)  # noqa: S102
    assert "BLIND" in ns["summary"]({"available": False, "error": "no artifact"})
