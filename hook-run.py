#!/usr/bin/env python3
"""hook-run.py <hook.py> [args...] -- run one Claude Code hook and record its outcome.

crew#391, 2026-08-27: 34 hook commands ran on every session start, prompt, tool use and
stop, and none recorded a verdict. Refusal rate, false refusals (LAW 38) and latency were
unmeasurable; `science/datamap.py --check` graded `hook/*` NEVER_EMITTED.

Incident 2026-09-01: settings.json ran `hook-run.py secret-scrub.py` with timeout=30s, but
hook-run's own TIMEOUT defaulted to 120s. When Claude Code killed hook-run at 30s, the grandchild
(secret-scrub) kept running in nobody's process group, with nobody to read its verdict (LAW 28).
Four copies of secret-scrub were observed with ppid=1, 28-50 minutes old, 60-70% CPU each, and
load average hit 41-88 on a 16GB Mac. Rule: a guard runs in its own process group and dies with
its wrapper.

This wrapper is the one place that measures. It passes stdin through, returns the hook's
stdout, stderr and exit code untouched, and appends one line per run to the ledger:

    {"at": ISO-8601 UTC, "event": hook_event_name, "hook": basename, "session": session_id,
     "exit": int, "ms": int, "refused": bool}

`waived` (crew#370) is the override marker the command carried when the hook passed it
(`# raw-diff-intended`, `# main-is-red`, `# in-flight`, ...). A refusal followed by a waived pass of
the same hook in the same session is a refusal the agent overturned; crew's hooks_row counts those
as false_refusals, the half of LAW 38 that had no writer.
`refused` is exit code 2 (Claude Code's block code) or a stdout JSON carrying
decision=block, continue=false or permissionDecision=deny. The ledger can never fail the
hook: every ledger error is swallowed, because a measurement that breaks the thing it
measures is an outage (LAW 38). Ledger path: $HOOK_OUTCOMES or ~/.claude/state/hook-outcomes.jsonl.
Reader: crew scripts/estate-snapshot hooks(), source `hook_outcomes` in science/sources.json.
"""

from __future__ import annotations

import atexit
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time

MARKER = re.compile(r"#\s*([a-z][a-z0-9-]*-intended|main-is-red|in-flight)\b")

LEDGER = os.environ.get("HOOK_OUTCOMES") or os.path.expanduser(
    "~/.claude/state/hook-outcomes.jsonl"
)


def refused(exit_code: int, stdout: bytes) -> bool:
    if exit_code == 2:
        return True
    try:
        out = json.loads(stdout.decode("utf-8", "replace") or "null")
    except ValueError:
        return False
    if not isinstance(out, dict):
        return False
    hso = (
        out.get("hookSpecificOutput")
        if isinstance(out.get("hookSpecificOutput"), dict)
        else {}
    )
    return (
        out.get("decision") == "block"
        or out.get("continue") is False
        or hso.get("permissionDecision") == "deny"
    )


def waived(payload: dict) -> str | None:
    ti = payload.get("tool_input")
    cmd = ti.get("command") if isinstance(ti, dict) else None
    m = MARKER.search(cmd) if isinstance(cmd, str) else None
    return m.group(1) if m else None


TIMEOUT = float(os.environ.get("HOOK_TIMEOUT") or 120)

# Global to hold the child process for signal handling
_child_pid = None


def _kill_child(signum, _frame):
    """Signal handler that kills the child process group and exits."""
    global _child_pid
    # Re-raise the signal with default handling after we do our cleanup,
    # but first block it to prevent recursive signals
    signal.signal(signum, signal.SIG_DFL)
    if _child_pid is not None:
        try:
            os.killpg(_child_pid, signal.SIGKILL)
        except OSError:
            pass  # Process already gone
    sig_name = signal.Signals(signum).name
    out = refusal("hook-run", f"hook-run was stopped by signal {sig_name}")
    sys.stdout.buffer.write(out.stdout)
    sys.stderr.buffer.write(out.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    # Use os._exit to bypass signal handling - we want exit code 2, not signal death
    os._exit(2)


def _atexit_kill_child():
    """atexit handler: kill child if still alive."""
    global _child_pid
    if _child_pid is not None:
        try:
            os.killpg(_child_pid, signal.SIGKILL)
        except OSError:
            pass  # Process already gone


def refusal(hook: str, why: str) -> subprocess.CompletedProcess:
    """crew#603 (founder 2026-08-28: "If a guard crashes, the answer is 'no'"). A guard that
    raised, was missing, or ran out of time used to return its own exit code (1) and Claude
    Code treated 1 as a warning: the action went ahead. Now every way a guard fails to reach a
    verdict is a refusal, exit 2 with a block decision, and the reason names the guard."""
    reason = f"{hook} could not reach a verdict, so the answer is no (fail-closed, crew#603): {why}"
    out = json.dumps(
        {
            "decision": "block",
            "reason": reason,
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
        }
    )
    return subprocess.CompletedProcess(
        args=[hook], returncode=2, stdout=out.encode(), stderr=(reason + "\n").encode()
    )


def run_closed(argv: list[str], stdin: bytes) -> subprocess.CompletedProcess:
    global _child_pid
    hook = os.path.basename(argv[0])
    if not os.path.isfile(argv[0]):
        return refusal(hook, f"no such file {argv[0]}")

    # Set up environment with deadline and pid for the child
    env = os.environ.copy()
    env["HOOK_DEADLINE"] = str(time.time() + TIMEOUT)
    env["HOOK_RUN_PID"] = str(os.getpid())

    # Register signal handlers
    signal.signal(signal.SIGTERM, _kill_child)
    signal.signal(signal.SIGHUP, _kill_child)
    signal.signal(signal.SIGINT, _kill_child)
    atexit.register(_atexit_kill_child)

    try:
        proc = subprocess.Popen(
            [sys.executable, *argv],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        _child_pid = proc.pid
        try:
            stdout, stderr = proc.communicate(input=stdin, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            # Kill the entire process group
            os.killpg(proc.pid, signal.SIGKILL)
            # Reap the process to avoid zombies
            proc.communicate()
            return refusal(hook, f"no verdict inside {TIMEOUT:g}s")
        _child_pid = None
        proc = subprocess.CompletedProcess(
            args=proc.args, returncode=proc.returncode, stdout=stdout, stderr=stderr
        )
    except OSError as e:
        return refusal(hook, f"could not start: {e}")
    if proc.returncode not in (0, 2):
        tail = (
            (proc.stderr or proc.stdout).decode("utf-8", "replace").strip().splitlines()
        )
        return refusal(
            hook, f"exit {proc.returncode}: {tail[-1] if tail else 'no output'}"
        )
    return proc


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
    proc = run_closed(argv, stdin)
    ms = int((time.monotonic() - t0) * 1000)
    sys.stdout.buffer.write(proc.stdout)
    sys.stderr.buffer.write(proc.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    row = {
        "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": payload.get("hook_event_name") or "unknown",
        "hook": os.path.basename(argv[0]),
        "session": (payload.get("session_id") or "nosession")[:8],
        "exit": proc.returncode,
        "ms": ms,
        "refused": refused(proc.returncode, proc.stdout),
    }
    marker = waived(payload)
    if marker and not row["refused"]:
        row["waived"] = marker
    record(row)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
