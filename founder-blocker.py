#!/usr/bin/env python3
"""The one command for a founder blocker (LAW 47 / R30). Founder, 2026-08-25, after missing the
Oracle sign-in twice: "i manage 8 agents concurrently, did you send to telegram also? i said it
needs to be loud". A terminal push is one channel of eight terminals; Telegram is the channel he
reads. This sends the blocker to the home channel, pins it, records the message_id in the
telegram ledger (blocker-guard.py refuses a FOUNDER ACTION: reply without that row) and prints
the FOUNDER ACTION: line to paste as reply line 2.

Usage: founder-blocker.py "<what he must do, one sentence>" [<url or word>] [--session ID]
Exit 0 with a message_id on screen, or 1 BLIND with the reason. Never raises.
"""
from __future__ import annotations

import json
import re
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from estate import estate_alert as ea
from estate import telegram_ledger

SOURCE = "founder-blocker"

# Incident 2026-08-26 (crew#269): a session pushed the catalogue password to the founder over
# Telegram in a FOUNDER ACTION. Founder: "not in line with our security principles". The class:
# a secret value placed in an outbound human channel. Refused here, where every session sends.
CREDENTIAL = re.compile(r"(password|passwd|passphrase|secret|token|api[_ -]?key|private[_ -]?key)\s*[:=]\s*\S{6,}", re.I)


def carries_credential(text: str) -> bool:
    return bool(CREDENTIAL.search(text)) or "BEGIN " in text and "PRIVATE KEY" in text


def _api(tok: str, method: str, **p):
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}",
                                 urllib.parse.urlencode(p).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def send(action: str, target: str = "", session: str = "") -> int:
    """Returns Telegram message_id (>0) or 0 when blind."""
    tok, chat = ea._env("TELEGRAM_BOT_TOKEN"), ea._env("TELEGRAM_HOME_CHANNEL")
    if not tok or not chat:
        print("BLIND: TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL missing", file=sys.stderr)
        return 0
    text = "FOUNDER ACTION: " + action.strip()
    if target:
        text += "\n" + target.strip()
    if carries_credential(text):
        telegram_ledger.record(SOURCE, "refused", "<credential-shaped text withheld>", key="credential")
        print("REFUSED: the text carries a credential (password/token/key value). A secret never travels "
              "over chat: put it in the vault and send the place, or use a login the founder already has.",
              file=sys.stderr)
        return 0
    if session:
        text += f"\n(session {session})"
    try:
        mid = int(_api(tok, "sendMessage", chat_id=chat, text=text[:4000],
                       disable_web_page_preview="true")["result"]["message_id"])
    except (OSError, ValueError, urllib.error.URLError, KeyError) as e:
        telegram_ledger.record(SOURCE, "error", text, key=str(e)[:80])
        print(f"BLIND: telegram send failed: {e}", file=sys.stderr)
        return 0
    try:
        _api(tok, "pinChatMessage", chat_id=chat, message_id=mid, disable_notification="false")
        pinned = "pinned"
    except (OSError, ValueError, urllib.error.URLError, KeyError) as e:
        pinned = f"not pinned ({e})"
    telegram_ledger.record(SOURCE, "sent", text, key=action[:60], msg_id=mid)
    print(f"telegram message_id={mid} {pinned}")
    print(text.splitlines()[0] + (" — " + target if target else ""))
    return mid


if __name__ == "__main__":
    argv, sess, args = sys.argv[1:], "", []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--session="):
            sess = a.split("=", 1)[1]
        elif a == "--session" and i + 1 < len(argv):
            sess = argv[i + 1]; i += 1
        else:
            args.append(a)
        i += 1
    if not args:
        print(__doc__); sys.exit(2)
    sys.exit(0 if send(args[0], args[1] if len(args) > 1 else "", sess) else 1)
