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

Fails CLOSED on every error since crew#603 (founder 2026-08-28: "If a guard crashes, the
answer is 'no'"). No OPA binary, an eval error, a payload it cannot read: each is a refusal
that names itself, never a silent pass. Until then it failed open, and a missing `opa` on
one Mac meant every rule in this directory was off with nobody told.

    echo '{"tool_name":"Artifact","tool_input":{"file_path":"/tmp/x.html"}}' \
      | python3 opa-hook.py

On the Stop event it reads the last assistant message from the transcript in the
payload and asks policy/reply.rego (query data.reply.deny) about the text above the
--- fold with code fences removed; a denial is printed as the hook's block decision.
That is the Stop runner hand_rolled_policy.rego was waiting for (crew#281 CP2).
"""
from __future__ import annotations

import calendar
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


class NoVerdict(Exception):
    """OPA could not be asked or did not answer. crew#603: that is a refusal, not a pass."""


def closed(why: str) -> str:
    return f"opa-hook could not reach a verdict, so the answer is no (fail-closed, crew#603): {why}"


def denials(payload: dict, query: str = QUERY) -> list[str]:
    opa = shutil.which("opa")
    if not opa:
        raise NoVerdict("no `opa` on PATH")
    try:
        out = subprocess.run(  # noqa: S603 - argv list, the opa binary from PATH, no shell
            [opa, "eval", "--strict-builtin-errors", "--format", "json",
             *sum(((["--ignore", p]) for p in IGNORE), []),
             "--data", POLICY, "--stdin-input", query],
            input=json.dumps(payload), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        raise NoVerdict(f"opa eval did not run: {e}") from e
    if out.returncode != 0:
        raise NoVerdict(f"opa eval exit {out.returncode}: {out.stderr.strip()[:300]}")
    try:
        return list(json.loads(out.stdout)["result"][0]["expressions"][0]["value"])
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise NoVerdict(f"opa answered in a shape this adapter cannot read: {e}") from e


def _above_fold(transcript_path: str) -> str:
    """Text of the last assistant message, cut at the first --- line. Nothing removed."""
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
    return "\n".join(kept)


def last_reply_above_fold(transcript_path: str) -> str:
    """The above-fold text with code fences blanked, which is what policy/reply.rego reads."""
    return re.sub(r"```.*?```", "", _above_fold(transcript_path), flags=re.S)


def reply_evidence(transcript_path: str) -> dict:
    """What Rego cannot see about the reply, measured here so the policy can decide.

    THE EMPIRICAL PROOF RULE (founder 2026-09-05). A MEASURED_OK claim has to carry a line the
    running system printed. Two facts are needed and neither survives into `reply`:

    - `reply_has_quote`: last_reply_above_fold() deletes fenced blocks outright, so by the time
      Rego sees the text every quoted log line is gone. The presence of a fence or a `> ` line is
      measured on the raw text instead.
    - `reply_asserted`: the reply's own voice, with backticks and quotations removed. A reply that
      writes MEASURED_OK inside backticks is naming the word, not claiming it -- the rule's first
      victim was the reply announcing the rule. Stripping those spans is what separates a claim
      from a mention.

    The adapter measures; policy/reply.rego decides.
    """
    raw = _above_fold(transcript_path)
    return {
        "reply_has_quote": bool(re.search(r"^\s*(?:```|>\s\S)", raw, re.M)),
        "reply_asserted": re.sub(
            r"^\s*>.*$", "", re.sub(r"`[^`]*`", "", re.sub(r"```.*?```", "", raw, flags=re.S)), flags=re.M
        ),
    }


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


def estate_snapshot() -> dict:
    """The cached estate state document (written by estate-state-relay.py at SessionStart), handed
    to the policies as input.estate. `fresh` is the one derived field: available, not stale, and
    fetched under 30 minutes ago. Everything else is the document, verbatim (crew#648 CP4)."""
    path = os.path.expanduser("~/.estate/estate-state.json")
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
        fetched = calendar.timegm(time.strptime(state["fetched_at"], "%Y-%m-%dT%H:%M:%SZ"))  # UTC in, UTC out; the Mac clock is BST
        age_min = (time.time() - fetched) / 60
    except (OSError, ValueError, KeyError, TypeError):
        return {"fresh": False}
    fresh = bool(state.get("available")) and not state.get("stale") and age_min < 30
    return {"fresh": fresh, "age_minutes": round(age_min, 1), "document": state.get("document") or {}}


def refuse(event: str, why: str) -> int:
    reason = closed(why)
    if event == "Stop":
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0
    print(json.dumps({"decision": "block", "reason": reason,
                      "hookSpecificOutput": {"permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.stderr.write(reason + "\n")
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as e:
        return refuse("unknown", f"payload is not JSON: {e}")
    if not isinstance(payload, dict):
        return refuse("unknown", "payload is not an object")
    event = str(payload.get("hook_event_name") or "unknown")
    try:
        return decide(payload, event)
    except NoVerdict as e:
        return refuse(event, str(e))


def decide(payload: dict, event: str) -> int:
    if event == "Stop":
        if payload.get("stop_hook_active"):
            return 0
        reply = last_reply_above_fold(str(payload.get("transcript_path", "")))
        payload_in = {"event": "Stop", "reply": reply, "focus": standing_focus(), "estate": estate_snapshot()}
        payload_in.update(reply_evidence(str(payload.get("transcript_path", ""))))
        age = checkpoint_age_s(str(payload.get("transcript_path", "")))
        if age is not None:
            payload_in["checkpoint_age_s"] = age
        msgs = denials(payload_in, REPLY_QUERY)
        if msgs:
            print(json.dumps({"decision": "block", "reason": "\n\n".join(sorted(msgs))}))
        return 0
    payload = {**payload, "estate": estate_snapshot()}
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
    except Exception as e:  # noqa: BLE001 - crew#603: a crashed adapter is a refusal
        raise SystemExit(refuse("unknown", f"{type(e).__name__}: {e}")) from None
