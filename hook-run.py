#!/usr/bin/env python3
"""hook-run.py <hook.py> [args...] -- run one Claude Code hook and record its outcome.

crew#391, 2026-08-27: 34 hook commands ran on every session start, prompt, tool use and
stop, and none recorded a verdict. Refusal rate, false refusals (LAW 38) and latency were
unmeasurable; `science/datamap.py --check` graded `hook/*` NEVER_EMITTED.

This wrapper is the one place that measures. It passes stdin through, returns the hook's
stdout, stderr and exit code untouched, and appends one line per run to the ledger:

    {"at": ISO-8601 UTC, "event": hook_event_name, "hook": basename, "session": session_id,
     "exit": int, "ms": int, "refused": bool}

`refused` is exit code 2 (Claude Code's block code) or a stdout JSON carrying
decision=block, continue=false or permissionDecision=deny. The ledger can never fail the
hook: every ledger error is swallowed, because a measurement that breaks the thing it
measures is an outage (LAW 38). Ledger path: $HOOK_OUTCOMES or ~/.claude/state/hook-outcomes.jsonl.
Reader: crew scripts/estate-snapshot hooks(), source `hook_outcomes` in science/sources.json.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time

LEDGER = os.environ.get("HOOK_OUTCOMES") or os.path.expanduser("~/.claude/state/hook-outcomes.jsonl")


def refused(exit_code: int, stdout: bytes) -> bool:
    if exit_code == 2:
        return True
    try:
        out = json.loads(stdout.decode("utf-8", "replace") or "null")
    except ValueError:
        return False
    if not isinstance(out, dict):
        return False
    hso = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
    return (out.get("decision") == "block" or out.get("continue") is False
            or hso.get("permissionDecision") == "deny")


def record(row: dict) -> None:
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write("usage: hook-run.py <hook> [args...]\n")
        return 0
    stdin = sys.stdin.buffer.read()
    try:
        payload = json.loads(stdin.decode("utf-8", "replace") or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    t0 = time.monotonic()
    proc = subprocess.run([sys.executable, *argv], input=stdin, capture_output=True)
    ms = int((time.monotonic() - t0) * 1000)
    sys.stdout.buffer.write(proc.stdout)
    sys.stderr.buffer.write(proc.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    record({
        "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": payload.get("hook_event_name") or "unknown",
        "hook": os.path.basename(argv[0]),
        "session": (payload.get("session_id") or "nosession")[:8],
        "exit": proc.returncode,
        "ms": ms,
        "refused": refused(proc.returncode, proc.stdout),
    })
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
