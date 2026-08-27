#!/usr/bin/env python3
"""Stop hook (LAW 47 / R30). A reply that says FOUNDER ACTION: must have reached the founder's
Telegram in the last 60 minutes through founder-blocker.py. Founder, 2026-08-25: "again i missed
it ... did you send to telegram also? i said it needs to be loud". The class: a founder blocker
announced only in a channel he is not watching. This guard cannot tell whether he read it; it
can tell whether a pinned message exists, and that is the receipt it demands.

crew#281 (founder, 2026-08-26): FOUNDER ACTION: is for a physical step only, and the staged form
("STAGED: ... Reply 'go' ... Auto-activating in N minutes.") must also have reached Telegram. Both
marks are graded against the ledger row founder-blocker.py wrote: outcome `sent` with a
`physical:` key, or outcome `staged`.

Exit 2 blocks the reply; exit 0 permits. BLIND (ledger unreadable) permits and says so.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WINDOW_S = 3600.0
MARK = "FOUNDER ACTION:"
MARK_STAGED = "STAGED:"


def last_assistant_text(transcript: Path) -> str:
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
                parts = [c.get("text", "") for c in row.get("message", {}).get("content", [])
                         if isinstance(c, dict) and c.get("type") == "text"]
                if parts:
                    text = "\n".join(parts)
    except OSError:
        return ""
    return text


def _row(ledger_rows: list[dict], now: float, outcome: str, key_prefix: str = "") -> bool:
    for r in ledger_rows:
        if r.get("source") == "founder-blocker" and r.get("outcome") == outcome \
                and str(r.get("key", "")).startswith(key_prefix) \
                and int(r.get("msg_id", 0) or 0) > 0 and now - float(r.get("ts", 0)) <= WINDOW_S:
            return True
    return False


def verdict(reply: str, ledger_rows: list[dict] | None, now: float) -> tuple[int, str]:
    wants_action, wants_staged = MARK in reply, MARK_STAGED in reply
    if not (wants_action or wants_staged):
        return 0, ""
    if ledger_rows is None:
        return 0, "[blocker-guard] BLIND: telegram ledger unreadable; FOUNDER ACTION:/STAGED: not checked"
    if wants_action and not _row(ledger_rows, now, "sent", "physical:"):
        return 2, ("BLOCKED by blocker-guard: the reply says FOUNDER ACTION: but no physical founder-blocker "
                   "Telegram message landed in the last 60 minutes (LAW 47 / R30; crew#281: FOUNDER ACTION: "
                   "is for a device in his hand, everything else is STAGED).\n"
                   "  physical  python3 ~/.claude/scripts/founder-blocker.py \"<the device step>\" <url-or-word> --physical\n"
                   "  else      python3 ~/.claude/scripts/founder-blocker.py \"<action>\" --staged [N]  and write STAGED:")
    if wants_staged and not _row(ledger_rows, now, "staged"):
        return 2, ("BLOCKED by blocker-guard: the reply says STAGED: but no staged founder-blocker Telegram "
                   "message landed in the last 60 minutes (crew#281: a staged action he cannot see cannot be held).\n"
                   "  run   python3 ~/.claude/scripts/founder-blocker.py \"<action>\" --staged [N]\n"
                   "  then  reissue the reply with the STAGED: line it prints")
    return 0, ""


def main() -> int:
    payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    reply = last_assistant_text(Path(payload.get("transcript_path") or "/dev/null"))
    try:
        from estate import telegram_ledger
        rows = telegram_ledger.read(since_s=time.time() - WINDOW_S)
    except (ImportError, OSError, ValueError):
        rows = None
    code, msg = verdict(reply, rows, time.time())
    if msg:
        print(msg, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
