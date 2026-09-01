#!/usr/bin/env python3
"""hook-run.py <hook.py> [args...] -- run one Claude Code hook and record its outcome.

crew#391, 2026-08-27: 34 hook commands ran on every session start, prompt, tool use and
stop, and none recorded a verdict. Refusal rate, false refusals (LAW 38) and latency were
unmeasurable; `science/datamap.py --check` graded `hook/*` NEVER_EMITTED.

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

import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time

MARKER = re.compile(r"#\s*([a-z][a-z0-9-]*-intended|main-is-red|in-flight)\b")

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


def waived(payload: dict) -> str | None:
    ti = payload.get("tool_input")
    cmd = ti.get("command") if isinstance(ti, dict) else None
    m = MARKER.search(cmd) if isinstance(cmd, str) else None
    return m.group(1) if m else None


# crew#787 (2026-09-01): this wrapper waited 120 s for its child while settings.json gave the
# harness 10 to 60 s per hook. The harness always won: it killed the wrapper, and the guard it
# had spawned lived on with no parent. Nine orphaned secret-scrub.py runs, each re-reading 844 MB
# of transcripts, drove the founder's Mac to load average 760 and made every local test timing a
# lie. So the budget is now read from the hook's own settings entry, two seconds under it, and the
# guard runs in its own process group that dies with the wrapper (see run_closed, _reap).
SETTINGS = os.environ.get("HOOK_SETTINGS") or os.path.expanduser("~/.claude/settings.json")
HARNESS_DEFAULT_S = 60.0   # Claude Code's own hook timeout when the entry names none
MARGIN_S = 2.0
FALLBACK_S = 120.0


def budget_s(hook: str, event: str | None) -> float:
    """Seconds this wrapper may wait for `hook`: $HOOK_TIMEOUT if set, else the smallest
    settings.json timeout for that hook under that event (or any event), minus MARGIN_S, floor 1;
    FALLBACK_S when settings.json cannot answer. Being under the harness's number is the whole
    point: the wrapper must be the one that reaps."""
    env = os.environ.get("HOOK_TIMEOUT")
    if env:
        return float(env)
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            hooks = json.load(fh).get("hooks") or {}
    except (OSError, ValueError, AttributeError):
        return FALLBACK_S
    found: list[float] = []
    for ev, rows in hooks.items():
        if event and ev != event:
            continue
        for row in rows if isinstance(rows, list) else []:
            for h in row.get("hooks", []) if isinstance(row, dict) else []:
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                if any(tok == hook or tok.endswith("/" + hook) for tok in cmd.split()):
                    found.append(float(h.get("timeout") or HARNESS_DEFAULT_S))
    if not found and event:
        return budget_s(hook, None)
    return max(1.0, min(found) - MARGIN_S) if found else FALLBACK_S


TIMEOUT = FALLBACK_S   # replaced per run by budget_s(); kept for readers of the ledger row text

_CHILD: subprocess.Popen | None = None


def _reap() -> None:
    """Kill the guard and everything it started. The guard runs in its own session (process
    group), so one signal reaches a child that forked."""
    child = _CHILD
    if child is None or child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            child.kill()
        except OSError:
            pass


def _harness_stopped_waiting(signum: int, _frame) -> None:
    """The harness gave up on this hook (SIGTERM or SIGHUP): take the guard down with us and
    answer as a refusal, so nothing survives the wrapper and nothing goes ahead unjudged."""
    _reap()
    hook = os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else "hook"
    out = refusal(hook, f"stopped by the harness (signal {signum}) before a verdict")
    try:
        sys.stdout.buffer.write(out.stdout)
        sys.stdout.flush()
    except OSError:
        pass
    os._exit(2)


def refusal(hook: str, why: str) -> subprocess.CompletedProcess:
    """crew#603 (founder 2026-08-28: "If a guard crashes, the answer is 'no'"). A guard that
    raised, was missing, or ran out of time used to return its own exit code (1) and Claude
    Code treated 1 as a warning: the action went ahead. Now every way a guard fails to reach a
    verdict is a refusal, exit 2 with a block decision, and the reason names the guard."""
    reason = f"{hook} could not reach a verdict, so the answer is no (fail-closed, crew#603): {why}"
    out = json.dumps({"decision": "block", "reason": reason,
                      "hookSpecificOutput": {"permissionDecision": "deny",
                                             "permissionDecisionReason": reason}})
    return subprocess.CompletedProcess(args=[hook], returncode=2, stdout=out.encode(),
                                       stderr=(reason + "\n").encode())


def run_closed(argv: list[str], stdin: bytes, timeout: float | None = None) -> subprocess.CompletedProcess:
    global _CHILD
    hook = os.path.basename(argv[0])
    if not os.path.isfile(argv[0]):
        return refusal(hook, f"no such file {argv[0]}")
    limit = TIMEOUT if timeout is None else timeout
    try:
        child = subprocess.Popen([sys.executable, *argv], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
    except OSError as e:
        return refusal(hook, f"could not start: {e}")
    _CHILD = child
    try:
        out, err = child.communicate(input=stdin, timeout=limit)
    except subprocess.TimeoutExpired:
        _reap()
        try:
            child.communicate(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return refusal(hook, f"no verdict inside {limit:g}s")
    finally:
        _CHILD = None
    proc = subprocess.CompletedProcess(args=child.args, returncode=child.returncode,
                                       stdout=out, stderr=err)
    if proc.returncode not in (0, 2):
        tail = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip().splitlines()
        return refusal(hook, f"exit {proc.returncode}: {tail[-1] if tail else 'no output'}")
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
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _harness_stopped_waiting)
    t0 = time.monotonic()
    proc = run_closed(argv, stdin, budget_s(os.path.basename(argv[0]), payload.get("hook_event_name")))
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
