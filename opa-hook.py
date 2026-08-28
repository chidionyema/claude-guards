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

import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
POLICY = os.environ.get("OPA_HOOK_POLICY") or os.path.join(HERE, "policy")
QUERY = "data.hooks.deny"
REPLY_QUERY = "data.reply.deny"
ADAPTER_EVENTS = {"SessionStart": "data.adapters.session_start",
                  "UserPromptSubmit": "data.adapters.user_prompt_submit",
                  "PreToolUse": "data.adapters.pre_tool_use",
                  "Stop": "data.adapters.stop"}

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
        out = subprocess.run(
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


BASH_EDIT = re.compile(r"\bsed -i\b|\bpython3? - <<|(?:^|[|;&\s])(?:cat|tee)\s*>")


def last_turn_edits(transcript_path: str) -> tuple[int, int]:
    """Edit tool calls since the last human message, and the distinct files they touched (reply.rego one-pass)."""
    count, files = 0, set()
    try:
        fh = open(transcript_path, encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") == "user":
                content = (row.get("message") or {}).get("content")
                human = isinstance(content, str) or (isinstance(content, list) and content and not any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content))
                if human:
                    count, files = 0, set()
                continue
            if row.get("type") != "assistant":
                continue
            for block in (row.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                inp = block.get("input") or {}
                if block.get("name") in ("Edit", "Write", "NotebookEdit"):
                    count += 1
                    files.add(str(inp.get("file_path") or inp.get("notebook_path") or "?"))
                elif block.get("name") == "Bash" and BASH_EDIT.search(str(inp.get("command", ""))):
                    count += 1
                    files.add("bash:" + str(inp.get("command", ""))[:40])
    return count, len(files)


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


def refuses(code: int, stdout: str) -> bool:
    if code == 2:
        return True
    try:
        out = json.loads(stdout or "null")
    except ValueError:
        return False
    if not isinstance(out, dict):
        return False
    hso = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
    return out.get("decision") == "block" or hso.get("permissionDecision") == "deny"


def run_adapters(payload: dict, event: str) -> int:
    """crew#603 CP4: SessionStart and UserPromptSubmit are one door each. The list of adapters
    that run, and their order, is policy (policy/adapters.rego); each runs through hook-run.py so a crash, a missing file
    or a timeout refuses the start instead of passing in silence. Their context is joined into
    one additionalContext, the shape Claude Code reads (code.claude.com/docs/en/hooks)."""
    rows = denials({"event": event}, ADAPTER_EVENTS[event])
    stdin = json.dumps(payload).encode()
    runner = os.path.join(HERE, "hook-run.py")
    parts: list[str] = []
    system: list[str] = []
    tool = str(payload.get("tool_name") or "")
    for row in rows:
        tools: list = []
        if isinstance(row, dict):
            tools = list(row.get("tools") or [])
            row = row.get("run")
        if not isinstance(row, list) or not row or not isinstance(row[0], str):
            raise NoVerdict(f"adapters row for {event} is not [name, args...]: {row!r}")
        if "archive/" in row[0]:
            raise NoVerdict(f"{row[0]} is archived and cannot run")
        if tools and tool not in tools:
            continue
        argv = [sys.executable, runner, os.path.join(HERE, row[0]), *map(str, row[1:])]
        try:
            proc = subprocess.run(argv, input=stdin, capture_output=True, timeout=150)
        except (OSError, subprocess.SubprocessError) as e:
            raise NoVerdict(f"{row[0]} did not run: {e}") from e
        text = proc.stdout.decode("utf-8", "replace")
        if event in ("PreToolUse", "Stop") and refuses(proc.returncode, text):
            # The adapter's refusal is the verdict; it passes through untouched so the
            # override marker and the one command it names reach the model as written.
            sys.stdout.write(text)
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
            return 2 if proc.returncode == 2 else 0
        if proc.returncode != 0:
            tail = (proc.stderr.decode("utf-8", "replace").strip() or text.strip()).splitlines()
            raise NoVerdict(f"{row[0]} exit {proc.returncode}: {tail[-1] if tail else 'no output'}")
        ctx = text.strip()
        try:
            out = json.loads(text)
            if isinstance(out, dict):
                hso = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
                ctx = str(hso.get("additionalContext") or "").strip()
                sm = str(out.get("systemMessage") or "").strip()
                if sm:
                    system.append(sm)
        except ValueError:
            pass
        if ctx:
            parts.append(ctx)
    out: dict = {}
    if event in ("SessionStart", "UserPromptSubmit"):
        # policy/session.rego decides what a session is told at its start (the one-pass
        # question, the canonical-root notice); the door only supplies the facts it needs.
        facts = {"event": event, "cwd": os.environ.get("CLAUDE_PROJECT_DIR") or str(payload.get("cwd") or os.getcwd()),
                 "home": os.path.expanduser("~")}
        try:
            told = denials(facts, "data.session.context")
        except NoVerdict:
            told = []  # a policy dir with no session.rego (the tests' minimal dirs) tells nothing
        parts[:0] = [str(t) for t in sorted(told, key=lambda t: not str(t).startswith("[canonical-root]"))]
    if parts:
        out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": "\n\n".join(parts)}
    if system:
        out["systemMessage"] = "\n\n".join(system)
    if out:
        print(json.dumps(out))
    return 0


def telegram_rows(window_s: float) -> list[dict] | None:
    """Rows founder-blocker.py wrote in the last window (blocker rules, LAW 47). None when the
    ledger cannot be read or imported: the reply.rego blocker rules treat a missing key as BLIND."""
    try:
        sys.path.insert(0, str(HERE))
        from estate import telegram_ledger  # noqa: PLC0415

        now = time.time()
        return [r for r in telegram_ledger.read(since_s=window_s)
                if now - float(r.get("ts") or 0) <= window_s]
    except Exception:  # noqa: BLE001
        return None


def decide(payload: dict, event: str) -> int:
    if event == "Stop":
        # reply.rego first (the rules already in Rego), then the Stop adapters in policy order.
        # Each adapter reads stop_hook_active for itself, as it did when settings ran it.
        if not payload.get("stop_hook_active"):
            reply = last_reply_above_fold(str(payload.get("transcript_path", "")))
            payload_in = {"event": "Stop", "reply": reply, "focus": standing_focus()}
            payload_in["turn_edits"], payload_in["turn_files"] = last_turn_edits(str(payload.get("transcript_path", "")))
            age = checkpoint_age_s(str(payload.get("transcript_path", "")))
            if age is not None:
                payload_in["checkpoint_age_s"] = age
            rows = telegram_rows(3600.0)
            if rows is not None:
                payload_in["telegram_ledger"] = rows  # absent = BLIND; blocker rules then permit
            msgs = denials(payload_in, REPLY_QUERY)
            if msgs:
                print(json.dumps({"decision": "block", "reason": "\n\n".join(sorted(msgs))}))
                return 0
        return run_adapters(payload, "Stop")
    if event in ADAPTER_EVENTS:
        rc = run_adapters(payload, event)
        if rc != 0 or event != "PreToolUse":
            return rc
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
        raise SystemExit(refuse("unknown", f"{type(e).__name__}: {e}"))
