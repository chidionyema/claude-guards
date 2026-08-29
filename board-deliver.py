#!/usr/bin/env python3
"""Hand a running session the board messages it has not seen yet.

The founder broadcast to every session twice on 2026-08-23, at 21:51 and 22:40.
Both landed on ~/.claude/ESTATE_BOARD.jsonl. Neither reached a single session,
and he said so: "Well didn't see any messages". He was right, and it was not a
Claude Code limitation. LAW 10 says every session is handed the board, and
nothing in settings.json ever did it. peer-loop-fence.py reads the board to
refuse a repeat; broadcast-check.sh reads a different file and nothing calls it.
Writing to the board was the half that existed. This is the reader, which is
where LAW 28 says the loop actually closes.

Runs on UserPromptSubmit, so a session that is already running receives a
broadcast on its next turn rather than only at startup, which is the case the
founder actually hit.

Each session keeps a cursor, so a message arrives once and then stops. Its own
writes never come back to it.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

BOARD = pathlib.Path(
    os.environ.get(
        "CLAUDE_ESTATE_BOARD", str(pathlib.Path.home() / ".claude" / "ESTATE_BOARD.jsonl")
    )
)
CURSOR_DIR = pathlib.Path.home() / ".claude" / "state" / "board-cursor"
MAX_SHOWN = 8            # a turn is not the place for a backlog dump
MAX_CHARS = 700          # per message, so one long post cannot eat the turn


def session_id() -> str:
    """Identify this session. Falls back to the project slug, then the pid's parent."""
    for var in ("CLAUDE_SESSION_ID", "CLAUDE_PROJECT_DIR"):
        val = os.environ.get(var)
        if val:
            return "".join(c if c.isalnum() else "-" for c in val)[-80:]
    return "unknown"


def read_board() -> list[dict]:
    """One object per line, and put the file right when it is not.

    On 2026-08-23 a writer appended pretty printed JSON to a JSONL file and 56
    of the board's 68 lines stopped parsing, the founder's own P0 among them. A
    reader that merely skips bad lines survives that and still loses the
    message, so this one recovers the objects and rewrites the file single line.
    LAW 6 puts self healing above a guard, and this needs no new instrument and
    no schedule: the next session to read the board repairs it.
    """
    if not BOARD.exists():
        return []
    raw = BOARD.read_text(encoding="utf-8", errors="replace")

    clean, ok = [], True
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            ok = False
            break
        if isinstance(obj, dict):
            clean.append(obj)
        else:
            ok = False
            break
    if ok:
        return clean

    # Stream every object out of the file regardless of how it was laid out:
    # pretty printed across lines, or two concatenated as `}{`.
    dec, out, i, n = json.JSONDecoder(), [], 0, len(raw)
    while i < n:
        while i < n and raw[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        try:
            obj, end = dec.raw_decode(raw, i)
        except json.JSONDecodeError:
            nl = raw.find("\n", i)
            if nl == -1:
                break
            i = nl + 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        i = end

    if out:
        out.sort(key=lambda o: str(o.get("ts", "")))
        tmp = BOARD.with_suffix(".jsonl.repair")
        tmp.write_text(
            "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out), encoding="utf-8"
        )
        os.replace(tmp, BOARD)   # atomic, so a concurrent reader never sees half a board
    return out


def sender(entry: dict) -> str:
    return str(entry.get("from") or entry.get("session") or entry.get("agent") or "?")


def body(entry: dict) -> str:
    """The readable content of a post.

    The board's fullest entry, The Architect's 22:37 status of all three
    sessions, carries a one line `message` and puts everything that answers the
    question in `detail`. Reading `message` alone delivers a headline and drops
    the report, so anything structured hanging off the post comes too.
    """
    text = entry.get("message") or entry.get("text") or entry.get("summary") or ""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    parts = [" ".join(text.split())]
    for key in ("detail", "details", "body", "data"):
        extra = entry.get(key)
        if extra in (None, "", {}, []):
            continue
        if isinstance(extra, str):
            parts.append(" ".join(extra.split()))
        else:
            parts.append(json.dumps(extra, ensure_ascii=False, separators=(", ", ": ")))
    return " ".join(p for p in parts if p).strip()


FOCUS_WORD = "FOCUS:"
FOCUS_FILE = pathlib.Path.home() / ".claude" / "state" / "goal" / "FOCUS.json"


def apply_focus(entries: list[dict], focus_file: pathlib.Path | None = None) -> int:
    """crew#395: a founder board line beginning FOCUS: becomes the standing focus, whichever
    channel wrote it. policy/reply.rego reads it (via opa-hook's standing_focus) and refuses a
    reply that asks him for a direction he has already given.

    crew#638 rewrote this. It used to load goal-guard and, through goal_focus.py, overwrite the
    goal field of every session state file. Both of those were deleted in the founder's triage
    for judging intent, so there are no session goal files left to rewrite -- only the standing
    line survives, and this writes it directly. Returns 1 when the file was written, 0 when the
    same text already stands, so N sessions delivering one line make one write.
    """
    path = focus_file or FOCUS_FILE
    total = 0
    for e in entries:
        if sender(e).lower() != "founder":
            continue
        text = body(e).strip()
        if not text.startswith(FOCUS_WORD):
            continue
        text = " ".join(text[len(FOCUS_WORD):].split())
        if not text:
            continue
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("text") == text:
                continue
        except (OSError, ValueError, AttributeError):
            pass                       # no focus on disk yet, or an unreadable one: write ours
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"text": text,
                                       "source": "board:" + str(e.get("ts") or ""),
                                       "at": int(time.time())}), encoding="utf-8")
            tmp.replace(path)          # replace, so a reader never sees half a focus
            total += 1
        except OSError:
            pass                       # a focus that cannot be written never blocks delivery
    return total


def main() -> int:
    me = session_id()
    entries = read_board()
    if not entries:
        return 0

    CURSOR_DIR.mkdir(parents=True, exist_ok=True)
    cursor_file = CURSOR_DIR / f"{me}.txt"
    seen = cursor_file.read_text(encoding="utf-8").strip() if cursor_file.exists() else ""

    # The board is append-ordered by timestamp. A cursor holding the last
    # delivered timestamp is enough, and it survives a repair that rewrites
    # the file, which an offset would not.
    fresh = []
    for e in entries:
        ts = str(e.get("ts") or "")
        if ts <= seen:
            continue
        if sender(e).lower() == me.lower():   # never echo a session to itself
            continue
        if not body(e):
            continue
        fresh.append(e)

    newest = max((str(e.get("ts") or "") for e in entries), default="")
    if newest:
        cursor_file.write_text(newest, encoding="utf-8")

    if not fresh:
        return 0

    # Priority first so a founder directive is never below a status update.
    def rank(e: dict) -> tuple:
        p = str(e.get("priority", "info")).lower()
        order = {"p0": 0, "critical": 0, "urgent": 0, "p1": 1, "warn": 2, "info": 3}
        return (order.get(p, 3), str(e.get("ts") or ""))

    # Newest first, then a stable sort by priority. A directive still comes
    # above a status update, but within a priority the recent post wins: the
    # first version of this dropped The Architect's 22:37 status of all three
    # sessions, the single most useful thing on the board, because four drill
    # notices from 21:41 sorted ahead of it and filled the window.
    fresh.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
    fresh.sort(key=lambda e: rank(e)[0])

    # The same post reaches the board twice when two writers relay it. The
    # founder's 22:40 directive is on there twice for exactly that reason, and
    # showing it twice reads as two orders.
    unique, seen_text = [], set()
    for e in fresh:
        key = (sender(e).lower(), body(e))
        if key in seen_text:
            continue
        seen_text.add(key)
        unique.append(e)
    fresh = unique
    apply_focus(fresh)

    shown, dropped = fresh[:MAX_SHOWN], max(0, len(fresh) - MAX_SHOWN)

    lines = [
        "[estate-board] MESSAGES ADDRESSED TO THIS SESSION THAT IT HAD NOT RECEIVED.",
        "A line marked founder is a direct instruction and outranks your current step.",
        "",
    ]
    for e in shown:
        who = sender(e)
        pri = str(e.get("priority", "info")).lower()
        mark = "FOUNDER" if who.lower() == "founder" else who
        tag = f" [{pri}]" if pri not in ("info", "") else ""
        text = body(e)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + " ..."
        lines.append(f"  {str(e.get('ts',''))[:19]} {mark}{tag}: {text}")
    if dropped:
        lines.append(f"  ... and {dropped} more on the board.")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a delivery bug must never block his prompt
        print(f"[estate-board] delivery failed: {exc}", file=sys.stderr)
        sys.exit(0)
