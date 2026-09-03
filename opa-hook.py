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


BLIND_BACKOFF_S = 60  # a blind session's refusals must stay under the hook's 15 s budget
REFETCH_TIMEOUT_S = 3  # three posts per fetch at most, so one re-fetch is under 10 s


def _relay():
    """estate-state-relay.py loaded by path (the file name has a hyphen). The hook re-uses the
    relay's fetch so there is one MCP client, not a second copy of it."""
    import importlib.machinery
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estate-state-relay.py")
    loader = importlib.machinery.SourceFileLoader("estate_state_relay", path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def _read_cache(path: str) -> tuple[dict, float]:
    with open(path, encoding="utf-8") as fh:
        state = json.load(fh)
    fetched = calendar.timegm(time.strptime(state["fetched_at"], "%Y-%m-%dT%H:%M:%SZ"))  # UTC in, UTC out; the Mac clock is BST
    return state, (time.time() - fetched) / 60


def _refetch(path: str, marker: str) -> str:
    """One re-fetch through the relay (the call SessionStart makes). Returns '' on success and
    the reason on failure; a failure is remembered in `marker` for BLIND_BACKOFF_S so a blind
    session is refused quickly rather than re-dialling the MCP on every tool call."""
    try:
        with open(marker, encoding="utf-8") as fh:
            last = json.load(fh)
        if time.time() - float(last.get("at", 0)) < BLIND_BACKOFF_S:
            return str(last.get("reason") or "the last fetch failed")
    except (OSError, ValueError, TypeError):
        pass
    try:
        relay = _relay()
        relay.TIMEOUT = REFETCH_TIMEOUT_S
        state = relay.fetch()
        state["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        try:
            os.remove(marker)
        except OSError:
            pass
        return ""
    except Exception as e:  # noqa: BLE001 - every failure is one blind reason, never a crash
        detail = str(getattr(e, "filename", None) or e)  # a missing file names the file, not a cut-off path
        if len(detail) > 160:
            detail = detail[:80] + " ... " + detail[-75:]
        reason = f"{type(e).__name__}: {detail}"
        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w", encoding="utf-8") as fh:
                json.dump({"at": time.time(), "reason": reason}, fh)
        except OSError:
            pass
        return reason


def estate_snapshot() -> dict:
    """The cached estate state document (written by estate-state-relay.py at SessionStart), handed
    to the policies as input.estate. `fresh` is the one derived field: available, not stale, and
    fetched under 30 minutes ago. Everything else is the document, verbatim (crew#648 CP4).

    Founder, 2026-09-03: "no agent can proceed without it." When the cache is missing, unavailable
    or older than 30 minutes, one re-fetch runs through the relay. If there is still no document
    the result is `blind`, with the reason; policy/hooks.rego and policy/reply.rego decide what a
    blind session may do (fetch, or reply BLOCKED:). This function decides nothing."""
    path = os.path.expanduser("~/.estate/estate-state.json")
    marker = os.path.expanduser("~/.estate/estate-state.blind.json")
    try:
        state, age_min = _read_cache(path)
    except (OSError, ValueError, KeyError, TypeError):
        state, age_min = {}, None
    if not state.get("available") or age_min is None or age_min >= 30:
        fetch_error = _refetch(path, marker)
        try:
            state, age_min = _read_cache(path)
        except (OSError, ValueError, KeyError, TypeError):
            state, age_min = {}, None
        if not state.get("available") or age_min is None:
            reason = fetch_error or str(state.get("reason") or "the estate MCP answered available=false")
            return {"fresh": False, "blind": True, "blind_reason": reason}
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
