#!/usr/bin/env python3
"""one-pass-guard: the founder's one-pass rule (AGENTS.md hard rule 5), on three events.

SessionStart / UserPromptSubmit: put the question in front of the agent before it edits:
"can this be batched?" — and the shape of the answer it must give (one line naming the pass).

Stop: measure, do not grade prose. Count the edits in the turn just finished: Edit/Write/
NotebookEdit tool calls plus in-place Bash edits (sed -i, python3 - <<, cat >). If the turn
made SERIAL_EDITS or more of them against DISTINCT_FILES or more files, that is one-at-a-time
work by construction; the reply then needs a `Batched:` line saying why it could not be one
pass (or that it was one pass and these are its files). Without it, the reply is refused.

Founder, 2026-08-28: "making excuses you could have fixed in one scripted pass without me
telling you", and the same hour: "can you be more efficient".
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

SERIAL_EDITS = 6
DISTINCT_FILES = 3
BATCH_LINE = re.compile(r"^\s*Batched:\s*\S", re.M)
BASH_EDIT = re.compile(r"\bsed -i\b|\bpython3? - <<|(?:^|[|;&\s])(?:cat|tee)\s*>")

QUESTION = (
    "[one-pass-guard] AGENTS.md hard rule 5, ONE PASS. Before the first edit ask: can this be "
    "batched? If several similar fixes are coming (the same lint over N files, the same rename, "
    "the same rung red in three PRs), write ONE script and run it once. Name the pass in one line "
    "before touching a file. A turn that edits 6+ times across 3+ files is refused at Stop unless "
    "the reply carries a `Batched:` line naming the pass or the reason there was none."
)


def last_turn_edits(transcript: pathlib.Path) -> tuple[int, set[str]]:
    """Edits since the last human message: (count, distinct files)."""
    count, files = 0, set()
    try:
        fh = transcript.open(encoding="utf-8", errors="replace")
    except OSError:
        return 0, set()
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") == "user":
                content = (row.get("message") or {}).get("content")
                # A tool_result row is also type=user; only a real human message resets the turn.
                if isinstance(content, str) or (isinstance(content, list) and content
                                                and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)):
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
    return count, files


def last_reply(transcript: pathlib.Path) -> str:
    text = ""
    try:
        with transcript.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") != "assistant":
                    continue
                parts = [b.get("text", "") for b in (row.get("message") or {}).get("content") or []
                         if isinstance(b, dict) and b.get("type") == "text"]
                if parts:
                    text = "\n".join(parts)
    except OSError:
        pass
    return text


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    event = payload.get("hook_event_name", "")
    if event in ("SessionStart", "UserPromptSubmit"):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": QUESTION}}))
        return 0
    if event != "Stop" or payload.get("stop_hook_active"):
        return 0
    tp = pathlib.Path(str(payload.get("transcript_path", "")))
    count, files = last_turn_edits(tp)
    if count >= SERIAL_EDITS and len(files) >= DISTINCT_FILES and not BATCH_LINE.search(last_reply(tp)):
        print(json.dumps({"decision": "block", "reason": (
            f"[one-pass-guard] this turn made {count} separate edits across {len(files)} files and the reply "
            f"has no `Batched:` line. AGENTS.md hard rule 5: similar fixes go in ONE scripted pass. "
            f"Add one line `Batched: <the pass you ran, or why these could not be one pass>` and reply again.")}))
    return 0


def selftest() -> int:
    import tempfile
    ok = True

    def ck(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    def row(kind, blocks):
        return json.dumps({"type": kind, "message": {"content": blocks}})

    def edit(i):
        return {"type": "tool_use", "name": "Edit", "input": {"file_path": f"/f{i}.py"}}

    with tempfile.TemporaryDirectory() as d:
        t = pathlib.Path(d) / "t.jsonl"
        t.write_text("\n".join([row("user", "go"), row("assistant", [edit(i) for i in range(6)]),
                                row("assistant", [{"type": "text", "text": "INVENTORY: x"}])]) + "\n")
        c, f = last_turn_edits(t)
        ck("six edits over six files counted", (c, len(f)) == (6, 6))
        ck("no Batched line -> refuse", not BATCH_LINE.search(last_reply(t)))
        t.write_text("\n".join([row("user", "go"), row("assistant", [edit(i) for i in range(6)]),
                                row("user", [{"type": "tool_result", "content": "x"}]),
                                row("assistant", [{"type": "text", "text": "DONE: y\nBatched: one ruff --fix pass"}])]) + "\n")
        c, f = last_turn_edits(t)
        ck("a tool_result row does not reset the turn", c == 6)
        ck("Batched line found", bool(BATCH_LINE.search(last_reply(t))))
        t.write_text("\n".join([row("assistant", [edit(i) for i in range(6)]), row("user", "next"),
                                row("assistant", [edit(1)])]) + "\n")
        ck("a human message resets the turn", last_turn_edits(t)[0] == 1)
        t.write_text("\n".join([row("user", "go"), row("assistant", [edit(1)] * 7)]) + "\n")
        c, f = last_turn_edits(t)
        ck("seven edits to ONE file is iteration, not serial fixing", len(f) < DISTINCT_FILES)
        ck("sed -i counts as an edit", BASH_EDIT.search("sed -i '' s/a/b/ x.py"))
    print("one-pass-guard selftest", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[one-pass-guard] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)
