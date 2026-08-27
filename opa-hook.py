#!/usr/bin/env python3
"""Ask OPA about a hook payload. Decides nothing itself.

This file exists so that policy does not. The rules it enforces are in
policy/hooks.rego, with their cases in policy/hooks_test.rego, and OPA 1.19.1 at
/usr/local/bin evaluates them. Two Python guards were deleted to create it:
vendor-surface-guard.py (146 lines) and adr-sources-guard.py (129 lines).

It carries no guard/gate/fence in its name on purpose. Those names mean "this
file decides something", and this one does not -- it reads stdin, hands it to the
engine, and prints what comes back. If a rule ever appears below this docstring,
the migration has gone backwards.

Fails OPEN on every error, deliberately. A broken adapter must not become an
outage on every tool call in every session (LAW 38).

    echo '{"tool_name":"Artifact","tool_input":{"file_path":"/tmp/x.html"}}' \
      | python3 opa-hook.py

On the Stop event it reads the last assistant message from the transcript in the
payload and asks policy/reply.rego (query data.reply.deny) about the text above the
--- fold with code fences removed; a denial is printed as the hook's block decision.
That is the Stop runner hand_rolled_policy.rego was waiting for (crew#281 CP2).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

POLICY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy")
QUERY = "data.hooks.deny"
REPLY_QUERY = "data.reply.deny"

# policy/fixtures holds JSON test data for other policies. Loading it as --data
# collides with itself ("merge error") and OPA then reports that as an empty
# result, which a fail-open adapter reads as "permitted". Same ignore list as
# rule-guard.py, and the reason it is not optional.
IGNORE = ("fixtures", "*.json")


def denials(payload: dict, query: str = QUERY) -> list[str]:
    opa = shutil.which("opa")
    if not opa:
        return []
    try:
        out = subprocess.run(
            [opa, "eval", "--strict-builtin-errors", "--format", "json",
             *sum(((["--ignore", p]) for p in IGNORE), []),
             "--data", POLICY, "--stdin-input", query],
            input=json.dumps(payload), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    try:
        return list(json.loads(out.stdout)["result"][0]["expressions"][0]["value"])
    except (ValueError, KeyError, IndexError, TypeError):
        return []


def last_reply_above_fold(transcript_path: str) -> str:
    """Text of the last assistant message, cut at the first --- line, code fences blanked."""
    text = ""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if row.get("type") != "assistant":
                    continue
                content = (row.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                joined = "\n".join(p for p in parts if p).strip()
                if joined:
                    text = joined
    except OSError:
        return ""
    kept = []
    for line in text.splitlines():
        if re.fullmatch(r"\s*-{3,}\s*", line):
            break
        kept.append(line)
    return re.sub(r"```.*?```", "", "\n".join(kept), flags=re.S)


def checkpoint_age_s(transcript_path):
    """Seconds since the project's checkpoints/LATEST.md was written; None when there is nothing to
    measure (crew#423 rows 16 and 25). None is BLIND, and the policy makes no verdict on it:
    - no transcript path: no project directory to look in;
    - no LATEST.md in the project: 3 of 8 active project dirs have never written one (#137 review),
      and a session that never wrote a checkpoint has not dropped a thread; a large number here was
      a refusal forever.
    A subagent's transcript sits at <project>/<session>/subagents/agent-*.jsonl, so the project
    directory is two levels up from there, not the subagents directory (#137 review: every subagent
    `git worktree add` was refused). The policy decides; this adapter only measures."""
    if not transcript_path:
        return None
    project = os.path.dirname(transcript_path)
    if os.path.basename(project) == "subagents":
        project = os.path.dirname(os.path.dirname(project))
    try:
        return int(time.time() - os.stat(os.path.join(project, "checkpoints", "LATEST.md")).st_mtime)
    except OSError:
        return None


def standing_focus() -> str:
    """The founder's standing FOCUS: line (goal_focus.py writes it), or '' when none is set.
    crew#395 / crew#398: policy/reply.rego holds a BLOCKED: reply to it; the file read is here
    because the policy decides and this adapter only gathers."""
    path = os.path.join(os.path.expanduser("~"), ".claude", "state", "goal", "FOCUS.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return str(json.load(fh).get("text") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if payload.get("hook_event_name") == "Stop":
        if payload.get("stop_hook_active"):
            return 0
        reply = last_reply_above_fold(str(payload.get("transcript_path", "")))
        payload_in = {"event": "Stop", "reply": reply, "focus": standing_focus()}
        age = checkpoint_age_s(str(payload.get("transcript_path", "")))
        if age is not None:
            payload_in["checkpoint_age_s"] = age
        msgs = denials(payload_in, REPLY_QUERY)
        if msgs:
            print(json.dumps({"decision": "block", "reason": "\n\n".join(sorted(msgs))}))
        return 0
    msgs = denials(payload)
    if not msgs:
        return 0
    sys.stderr.write("\n\n".join(sorted(msgs)) + "\n")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)
