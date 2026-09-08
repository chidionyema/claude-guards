#!/usr/bin/env python3
"""Stop hook (LAW 47 / R30). A reply that says FOUNDER ACTION: or STAGED: must have reached the
founder's Telegram in the last hour through founder-blocker.py.

This file decides nothing. The rules are policy/blocker.rego and their cases are in
policy/blocker_test.rego; what is left here is the two things OPA cannot read for itself -- the
reply out of the transcript, and the telegram ledger -- plus the one transform the rules are cut
on: fenced blocks dropped and inline code spans blanked, so that NAMING a mark is not asking for
anything. That transform is why this guard stopped refusing the reply "I wrote `FOUNDER ACTION:`
for something that is not a device-in-hand step" on 2026-09-07.

Exit 2 blocks the reply; exit 0 permits. BLIND (no opa, or an unreadable ledger) permits and says
so: a guard that blocks on its own blindness stops every reply the moment a file moves.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WINDOW_S = 3600.0
POLICY = Path(__file__).resolve().parent / "policy"
_FENCE = re.compile(r"^\s{0,3}(?:```|~~~)")
_SPAN = re.compile(r"`+[^`\n]*`+")


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
                parts = [
                    c.get("text", "")
                    for c in row.get("message", {}).get("content", [])
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                if parts:
                    text = "\n".join(parts)
    except OSError:
        return ""
    return text


def prose(reply: str) -> str:
    """`reply` with fenced blocks dropped and inline code spans blanked."""
    out, in_fence = [], False
    for line in reply.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(_SPAN.sub(" ", line))
    return "\n".join(out)


def denials(reply: str, rows: list[dict] | None, now: float) -> list[str]:
    opa = shutil.which("opa")  # the rules live in policy/blocker.rego
    if not opa:
        return []
    out = subprocess.run(  # noqa: S603  argv list, no shell, our own paths
        [opa, "eval", "--format", "json", "--ignore", "fixtures", "--ignore", "*.json",
         "--data", str(POLICY), "--stdin-input", "data.blocker.deny"],
        input=json.dumps({
            "reply": prose(reply),
            "rows": rows or [],
            "now": now,
            "ledger_readable": rows is not None,
        }),
        capture_output=True, text=True, timeout=10,
    )
    if out.returncode != 0:
        return []
    return sorted(json.loads(out.stdout)["result"][0]["expressions"][0]["value"])


def main() -> int:
    payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    reply = last_assistant_text(Path(payload.get("transcript_path") or "/dev/null"))
    try:
        from estate import telegram_ledger

        rows = telegram_ledger.read(since_s=time.time() - WINDOW_S)
    except (ImportError, OSError, ValueError):
        rows = None
    if rows is None:
        print("[blocker-guard] BLIND: telegram ledger unreadable; the marks were not checked",
              file=sys.stderr)
    msgs = denials(reply, rows, time.time())
    if not msgs:
        return 0
    print("\n".join(msgs), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
