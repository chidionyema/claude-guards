"""crew#391 incident, 2026-08-27: 34 hook commands ran on every event and none recorded a
verdict, so refusal rate, false refusals (LAW 38) and latency could not be measured.

Rules. (1) hook-run.py returns the hook's stdout and exit code untouched and appends one
ledger row, refused=false for a pass and refused=true for a block, in the same run. (2) Every
hook command in settings/settings.json goes through hook-run.py, so a hook added tomorrow
cannot skip the ledger. Closed world: the count of wrapped commands equals the count of commands.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RUN = HERE / "hook-run.py"
SETTINGS = HERE / "settings" / "settings.json"

PASS_HOOK = "import sys; sys.stdin.read(); print('all good'); sys.exit(0)"
BLOCK_HOOK = ("import sys, json; sys.stdin.read(); "
              "print(json.dumps({'decision': 'block', 'reason': 'no'})); sys.exit(2)")


def _run(tmp_path: Path, body: str, name: str):
    hook = tmp_path / name
    hook.write_text(body)
    ledger = tmp_path / "hook-outcomes.jsonl"
    payload = json.dumps({"hook_event_name": "Stop", "session_id": "abcdef0123"})
    proc = subprocess.run([sys.executable, str(RUN), str(hook)], input=payload, text=True,
                          capture_output=True, env={**os.environ, "HOOK_OUTCOMES": str(ledger)})
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    return proc, rows


def test_pass_and_block_are_recorded_and_passed_through(tmp_path):
    ok, rows = _run(tmp_path, PASS_HOOK, "ok.py")
    assert ok.returncode == 0 and ok.stdout == "all good\n"
    assert len(rows) == 1 and rows[0]["refused"] is False and rows[0]["exit"] == 0
    assert rows[0]["event"] == "Stop" and rows[0]["hook"] == "ok.py" and rows[0]["session"] == "abcdef01"
    assert isinstance(rows[0]["ms"], int)

    no, rows = _run(tmp_path, BLOCK_HOOK, "no.py")
    assert no.returncode == 2 and json.loads(no.stdout)["decision"] == "block"
    assert len(rows) == 2 and rows[1]["refused"] is True and rows[1]["exit"] == 2


def test_ledger_failure_never_fails_the_hook(tmp_path):
    hook = tmp_path / "ok.py"
    hook.write_text(PASS_HOOK)
    proc = subprocess.run([sys.executable, str(RUN), str(hook)], input="{}", text=True,
                          capture_output=True,
                          env={**os.environ, "HOOK_OUTCOMES": str(tmp_path / "ok.py" / "x.jsonl")})
    assert proc.returncode == 0 and proc.stdout == "all good\n"


def test_every_settings_hook_goes_through_hook_run():
    s = json.loads(SETTINGS.read_text())
    commands = [h["command"] for groups in s.get("hooks", {}).values()
                for g in groups for h in g.get("hooks", []) if h.get("type", "command") == "command"]
    assert commands, "settings.json wires no hooks; the closed world is empty"
    naked = [c for c in commands if "/hook-run.py " not in c]
    assert naked == [], f"{len(naked)} of {len(commands)} hook commands skip the outcome ledger: {naked}"
