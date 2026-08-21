#!/usr/bin/env python3
"""Read back everything the founder has ever said, in one command.

Pairs with `directive-capture.py`, the UserPromptSubmit hook that appends each message as it is
sent. This side does two jobs:

  --backfill   mine the existing transcript .jsonl files into the same log, once, so the record
               starts at the beginning of the project and not at the day the hook was installed.
  (default)    search and print, newest last, so an agent can answer "what did he say about X"
               without writing a bespoke scanner for the fifth time.

Examples:
    python3 ~/.claude/scripts/directives.py --backfill
    python3 ~/.claude/scripts/directives.py --grep 'laptop|emergenc' --limit 40
    python3 ~/.claude/scripts/directives.py --since 2026-08-18 --full
"""
from __future__ import annotations

import argparse
import json
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
LOG_DIR = HOME / ".claude" / "directives"
PROJECTS = HOME / ".claude" / "projects"

# One global item ledger, not one per project. A request the founder makes in any window belongs on
# the same board, and a per-project split is how "he asked twice" happens: the second session looks
# in its own slug and sees nothing. Append-only events, folded on read -- no rewrite, so two sessions
# opening items at the same moment cannot lose each other's line.
ITEMS = Path(os.environ.get("DIRECTIVE_ITEMS", LOG_DIR / "items.jsonl"))

# Harness-injected text that arrives shaped like a user turn but is not the founder speaking.
NOISE = re.compile(
    r"^(<command-name>|<local-command|<system-reminder>|Caveat: The messages below|"
    r"\[Request interrupted|<user-prompt-submit-hook>|This session is being continued|"
    r"<cross-session-message|<task-notification)",
)


def slug_for(cwd: str) -> str:
    return cwd.replace("/", "-") or "-unknown"


def log_path(cwd: str) -> Path:
    return LOG_DIR / f"{slug_for(cwd)}.jsonl"


def _text_of(msg: dict) -> str:
    """A user message's content is either a string or a list of blocks."""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""



def _queued_human_prompt(rec: dict) -> str | None:
    """Text of a message the founder queued mid-turn, or None if this is not one.

    The harness does not run UserPromptSubmit for these, so directive-capture.py never sees them.
    The transcript records them as an attachment rather than as a user message. The origin check
    keeps out queued work the harness itself enqueues.
    """
    if rec.get("type") != "attachment":
        return None
    att = rec.get("attachment") or {}
    if att.get("type") != "queued_command":
        return None
    if (att.get("origin") or {}).get("kind") != "human":
        return None
    return att.get("prompt") or None



def selftest() -> int:
    """Prove the two things that were broken on 2026-08-20, so neither can come back silently.

    Run:  python3 ~/.claude/scripts/directives.py --selftest
    """
    line = json.dumps({
        "type": "attachment",
        "attachment": {"type": "queued_command", "prompt": "nission cuticl",
                       "commandMode": "prompt", "origin": {"kind": "human"},
                       "timestamp": "2026-08-20T20:33:20.091Z"},
        "timestamp": "2026-08-20T20:33:20.091Z",
        "session_id": "s", "userType": "external",
    })
    failures = []
    # 1. The cheap prefilter must let it through. It does NOT contain the substring '"user"'.
    if '"user"' in line:
        failures.append("the fixture no longer exercises the prefilter hole; rebuild it")
    if not ('"user"' in line or "queued_command" in line):
        failures.append("prefilter would drop a queued human directive")
    # 2. The extractor must recognise it, and must reject a non-human queued command.
    if _queued_human_prompt(json.loads(line)) != "nission cuticl":
        failures.append("_queued_human_prompt does not read a queued human directive")
    robot = json.loads(line)
    robot["attachment"]["origin"] = {"kind": "harness"}
    if _queued_human_prompt(robot) is not None:
        failures.append("_queued_human_prompt accepts a queued command that is not the founder's")
    # 3. Harness envelopes are not directives.
    for envelope in ("<cross-session-message from=x>", "<task-notification>", "<system-reminder>"):
        if not NOISE.match(envelope):
            failures.append(f"NOISE does not filter {envelope!r}")
    for real in ("nission cuticl", "we ned trackinng etrene"):
        if NOISE.match(real):
            failures.append(f"NOISE filters a real directive: {real!r}")
    for f in failures:
        print("FAIL:", f, file=sys.stderr)
    print("selftest: PASS" if not failures else f"selftest: {len(failures)} FAILURE(S)")
    return 1 if failures else 0


def backfill(cwd: str) -> int:
    """Mine transcripts for user turns and merge them into the log. Idempotent: dedupes on text."""
    proj = PROJECTS / slug_for(cwd)
    if not proj.is_dir():
        print(f"no transcript directory at {proj}", file=sys.stderr)
        return 1
    path = log_path(cwd)
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                seen.add(json.loads(line)["prompt"][:200])
            except Exception:
                continue
    rows: list[dict] = []
    for tr in sorted(proj.glob("*.jsonl")):
        try:
            fh = tr.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                # Cheap prefilter, and it needs BOTH terms. A queued_command attachment does
                # not contain the substring '"user"' at all -- its nearest field is "userType",
                # which has no closing quote after "user" -- so matching on '"user"' alone drops
                # every mid-turn directive. Measured 2026-08-20: that is exactly what it did.
                if '"user"' not in line and "queued_command" not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                queued = _queued_human_prompt(rec)
                if queued is not None:
                    text, rec = queued, {"timestamp": rec.get("timestamp", ""),
                                         "sessionId": rec.get("session_id", "")}
                else:
                    msg = rec.get("message") or {}
                    if msg.get("role") != "user" or rec.get("isMeta"):
                        continue
                    text = _text_of(msg)
                text = text.strip()
                if not text or text.startswith("/") or NOISE.match(text):
                    continue
                key = text[:200]
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "ts": rec.get("timestamp", ""),
                    "session": rec.get("sessionId", ""),
                    "cwd": cwd,
                    "prompt": text,
                })
    rows.sort(key=lambda r: r["ts"])
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"backfilled {len(rows)} message(s) into {path}")
    return 0


def read(cwd: str, pattern: str | None, since: str | None, limit: int, full: bool) -> int:
    path = log_path(cwd)
    if not path.exists():
        print(f"no log at {path} — run with --backfill first", file=sys.stderr)
        return 1
    rx = re.compile(pattern, re.I) if pattern else None
    hits = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if since and row.get("ts", "") < since:
            continue
        if rx and not rx.search(row.get("prompt", "")):
            continue
        hits.append(row)
    hits.sort(key=lambda r: r.get("ts", ""))
    for row in hits[-limit:]:
        text = row["prompt"] if full else row["prompt"][:600]
        print(f"\n--- {row.get('ts', '?')}")
        print(text)
    print(f"\n{len(hits)} match(es); showing the last {min(limit, len(hits))}.")
    return 0



# --------------------------------------------------------------------------- LAW 18 item ledger

VALID = ("open", "done", "blocked")


def _append(row: dict) -> None:
    ITEMS.parent.mkdir(parents=True, exist_ok=True)
    with ITEMS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def items() -> dict[str, dict]:
    """Fold the event log into the current state of every item, oldest first."""
    out: dict[str, dict] = {}
    if not ITEMS.exists():
        return out
    for line in ITEMS.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        rid = ev.get("id")
        if not rid:
            continue
        if ev.get("event") == "open":
            out[rid] = {"id": rid, "opened": ev.get("ts", ""), "text": ev.get("text", ""),
                        "cwd": ev.get("cwd", ""), "session": ev.get("session", ""),
                        "state": "open", "note": "", "closed": ""}
        elif rid in out:
            # A close is never silent about its evidence: --proof is required at the CLI, so a
            # done item always carries the line that proved it. LAW 17 lives or dies here.
            out[rid]["state"] = "done" if ev.get("event") == "close" else "blocked"
            out[rid]["note"] = ev.get("note", "")
            out[rid]["closed"] = ev.get("ts", "")
    return out


def open_item(text: str, cwd: str) -> int:
    text = (text or "").strip()
    if not text:
        print("--open needs the founder's words", file=sys.stderr)
        return 2
    ts = _now()
    rid = "REQ-" + hashlib.sha256((ts + text).encode("utf-8")).hexdigest()[:8]
    _append({"ts": ts, "id": rid, "event": "open", "text": text, "cwd": cwd,
             "session": os.environ.get("CLAUDE_SESSION_ID", "")})
    print(rid)
    return 0


def settle(rid: str, event: str, note: str) -> int:
    note = (note or "").strip()
    if not note:
        print(f"--{'proof' if event == 'close' else 'why'} is required", file=sys.stderr)
        return 2
    known = items()
    if rid not in known:
        print(f"no such item: {rid}. Open ones: "
              + (", ".join(k for k, v in known.items() if v["state"] == "open") or "none"),
              file=sys.stderr)
        return 1
    _append({"ts": _now(), "id": rid, "event": event, "note": note})
    print(f"{rid} {'done' if event == 'close' else 'blocked'}")
    return 0


def show_items(as_json: bool) -> int:
    all_items = items()
    rows = sorted(all_items.values(), key=lambda r: r["opened"])
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in VALID}
    if as_json:
        print(json.dumps({"items": rows, **counts, "ledger": str(ITEMS)}, ensure_ascii=False))
        return 0
    for r in rows:
        if r["state"] == "done":
            continue
        print(f"{r['id']}  {r['state']:<7} {r['opened'][:16]}  {r['text'][:90]}")
    print(f"\n{counts['open']} open, {counts['blocked']} blocked, {counts['done']} done "
          f"({ITEMS})")
    return 0


def selftest_items() -> int:
    """Prove the ledger end to end in a scratch file, never the real one."""
    import tempfile
    global ITEMS
    real = ITEMS
    fails = []
    with tempfile.TemporaryDirectory() as d:
        ITEMS = Path(d) / "items.jsonl"
        buf, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            open_item("track every founder request", "/tmp")
            rid = next(iter(items()))
            settle(rid, "close", "grep printed the row")
            bad = settle("REQ-nope", "close", "x")
            empty = settle(rid, "close", "   ")
        finally:
            sys.stdout.close()
            sys.stdout = buf
        st = items()[rid]
        if st["state"] != "done":
            fails.append(f"close did not stick: {st['state']}")
        if st["note"] != "grep printed the row":
            fails.append("proof was not recorded")
        if bad != 1:
            fails.append("closing an unknown id did not fail")
        if empty != 2:
            fails.append("a close with no proof was accepted")
    ITEMS = real
    for f in fails:
        print("FAIL " + f)
    print("items ledger: " + ("PASS" if not fails else f"{len(fails)} FAIL"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Search everything the founder has said in a project.")
    ap.add_argument("--cwd", default=str(HOME / "Documents" / "code" / "prospector"),
                    help="project root whose log to read (default: prospector)")
    ap.add_argument("--backfill", action="store_true", help="mine transcripts into the log, then exit")
    ap.add_argument("--selftest", action="store_true", help="prove mid-turn capture still works")
    ap.add_argument("--grep", help="regex, case-insensitive")
    ap.add_argument("--since", help="ISO date, e.g. 2026-08-18")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--full", action="store_true", help="print whole messages, not the first 600 chars")
    ap.add_argument("--open", metavar="TEXT", help="LAW 18: open a tracked item in his words; prints its id")
    ap.add_argument("--close", metavar="REQ-ID", help="LAW 18: close an item; needs --proof")
    ap.add_argument("--block", metavar="REQ-ID", help="LAW 18: park an item; needs --why")
    ap.add_argument("--proof", help="the command output that proves the item is done")
    ap.add_argument("--why", help="what is stopping a blocked item")
    ap.add_argument("--items", action="store_true", help="LAW 18: what is open right now")
    ap.add_argument("--json", action="store_true", help="machine-readable --items, for the board")
    args = ap.parse_args()
    if args.selftest:
        return selftest() or selftest_items()

    if args.open:
        return open_item(args.open, args.cwd)
    if args.close:
        return settle(args.close, "close", args.proof or "")
    if args.block:
        return settle(args.block, "blocked", args.why or "")
    if args.items:
        return show_items(args.json)

    if args.backfill:
        return backfill(args.cwd)
    return read(args.cwd, args.grep, args.since, args.limit, args.full)


if __name__ == "__main__":
    sys.exit(main())
