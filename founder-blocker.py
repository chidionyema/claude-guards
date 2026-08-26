#!/usr/bin/env python3
"""The one command for a founder blocker (LAW 47 / R30). Founder, 2026-08-25, after missing the
Oracle sign-in twice: "i manage 8 agents concurrently, did you send to telegram also? i said it
needs to be loud". A terminal push is one channel of eight terminals; Telegram is the channel he
reads. This sends the blocker to the home channel, pins it, records the message_id in the
telegram ledger (blocker-guard.py refuses a FOUNDER ACTION: reply without that row) and prints
the FOUNDER ACTION: line to paste as reply line 2.

Founder directive 2026-08-26 (crew#281, "lazy consensus"): FOUNDER ACTION: is restricted to a
physical step, a device in his hand. Everything else is staged with a default and a timer:
  STAGED: <action> is ready. Reply 'go' to execute immediately, 'hold' to review. Auto-activating in N minutes.
The staging session owns the timer: it executes at N minutes unless 'hold' arrives.

Usage: founder-blocker.py "<action, one sentence>" [<url or word>] [--session ID] [--staged [N]] [--physical]
  default            STAGED with the estate timeout (estate-defaults.yaml handoff_protocol.timeout_minutes, else 60)
  --staged N         STAGED with N minutes
  --physical         FOUNDER ACTION: permitted only when the text names the physical thing
  --register ROW     with --physical: the Capabilities register row (~/AGENTS.md) you checked, or `none`.
                     A row that exists is a self-serve path and the send is refused (crew#325: four
                     sessions sent "create the GitHub App" for a deploy key any session can mint).
Exit 0 with a message_id on screen, or 1 BLIND/REFUSED with the reason. Never raises.
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
REGISTER = os.path.expanduser("~/AGENTS.md")
REGISTER_HEAD = "# Capabilities register"


def register_rows(path: str = REGISTER) -> list[tuple[str, str]]:
    """(need, self-serve path) rows of the Capabilities register table in ~/AGENTS.md; [] if absent."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return []
    if REGISTER_HEAD not in text:
        return []
    rows = []
    for line in text.split(REGISTER_HEAD, 1)[1].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] not in ("Need", "") and not set(cells[0]) <= set("-"):
            rows.append((cells[0], cells[1]))
    return rows


def register_match(claim: str, rows: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The row whose Need column the claim names (case-insensitive, either contains the other)."""
    c = claim.strip().lower()
    for need, path in rows:
        n = need.lower()
        if c and (c in n or n in c):
            return need, path
    return None


# Incident 2026-08-26 (crew#269): a session pushed the catalogue password to the founder over
# Telegram in a FOUNDER ACTION. Founder: "not in line with our security principles". The class:
# a secret value placed in an outbound human channel. Refused here, where every session sends.
CREDENTIAL = re.compile(r"(password|passwd|passphrase|secret|token|api[_ -]?key|private[_ -]?key)\s*[:=]\s*\S{6,}", re.I)


# crew#281: the only step a person must take is one a token or an API cannot: a device in his hand.
# A step that is not physical is staged with a default; the API side is code (idp platform/access).
PHYSICAL = re.compile(r"\b(hardware key|security key|yubikey|passkey|touch id|face id|fingerprint|phone|handset|"
                      r"laptop|usb|sim card|cable|plug|badge|power (?:button|cord|socket)|in (?:his|your) hand)\b", re.I)
# A console step dressed in a physical word ("device flow", "share your screen", "power-cycle from
# the console") is the incident shape; a URL or a console word in the text refuses it outright.
CONSOLE = re.compile(r"https?://|\b(console|dashboard|settings|portal|browser|web ?ui|device flow|sign[- ]?in page)\b", re.I)
DEFAULT_TIMEOUT_MIN = 60


def names_physical(text: str) -> bool:
    return bool(PHYSICAL.search(text)) and not CONSOLE.search(text)


# Only the template's own approval clause is stripped: "[is ready.] Reply '<word>' to execute
# now|immediately, 'hold' to cancel|review. [Auto-activating in N minutes.]" A looser pattern
# (guards#69 review, 2026-08-26) cut "reply 'ok' once the migration completes" out of a real
# action. Text that merely resembles the template is the founder's and stays.
_TEMPLATE_TAIL = re.compile(
    r"\s*\.?\s*(is ready\.\s*)?Reply '[^']*' to execute (now|immediately),\s*'hold' to (cancel|review)\."
    r"(\s*Auto-activating in \d+ minutes?\.?)?\s*$", re.I)


def normalise_action(action: str) -> str:
    """The caller passes the action phrase; this script owns the STAGED sentence.

    2026-08-26 (session 9f8f4f5f, msg 14076): a caller pasted the whole template as the
    action and the channel read "STAGED: STAGED: ... Auto-activating in 60 minutes is ready.
    Reply 'go' ... Auto-activating in 60 minutes." Strip a leading STAGED:/FOUNDER ACTION:
    label and any trailing template phrases, repeatedly, so the sentence is composed once.
    """
    a = action.strip()
    while True:
        before = a
        a = re.sub(r"^\s*(STAGED|FOUNDER ACTION)\s*:\s*", "", a, flags=re.I)
        a = _TEMPLATE_TAIL.sub("", a).strip()
        if a == before:
            return a.rstrip(".")


def staged_text(action: str, minutes: int) -> str:
    return (f"STAGED: {normalise_action(action)} is ready. Reply 'go' to execute immediately, "
            f"'hold' to review. Auto-activating in {minutes} minutes.")


def default_timeout() -> int:
    """handoff_protocol.timeout_minutes from the estate's defaults file when one is on disk; else 60."""
    for root in (os.environ.get("ESTATE_CODE"), os.path.join(os.path.expanduser("~"), "dev", "code")):
        f = os.path.join(root or "", "idp", "estate-defaults.yaml")
        if root and os.path.exists(f):
            m = re.search(r"^\s*timeout_minutes:\s*(\d+)", open(f, encoding="utf-8").read(), re.M)
            if m:
                return int(m.group(1))
    return DEFAULT_TIMEOUT_MIN


def carries_credential(text: str) -> bool:
    return bool(CREDENTIAL.search(text)) or "BEGIN " in text and "PRIVATE KEY" in text


def _api(tok: str, method: str, **p):
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}",
                                 urllib.parse.urlencode(p).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def send(action: str, target: str = "", session: str = "", *, staged_minutes: int | None = None,
         physical: bool = False, register: str | None = None) -> int:
    """Returns Telegram message_id (>0) or 0 when blind or refused."""
    if physical:
        rows = register_rows()
        if register is None:
            telegram_ledger.record(SOURCE, "refused", action, key="register-unchecked")
            table = "\n".join(f"  {n}  ->  {p}" for n, p in rows) or "  (register unreadable: ~/AGENTS.md has no Capabilities register)"
            print("REFUSED: FOUNDER ACTION: needs --register <row|none>: name the Capabilities register row "
                  "you checked (crew#325: a day went to 'create the GitHub App' that a deploy key replaced). "
                  "Rows:\n" + table, file=sys.stderr)
            return 0
        hit = None if register.strip().lower() == "none" else register_match(register, rows)
        if hit:
            telegram_ledger.record(SOURCE, "refused", action, key="self-serve:" + hit[0][:40])
            print(f"REFUSED: a self-serve path exists for '{hit[0]}': {hit[1]}\nDo that instead; "
                  "FOUNDER ACTION: is only for what no session can do.", file=sys.stderr)
            return 0
    if physical and not names_physical(action):
        telegram_ledger.record(SOURCE, "refused", action, key="not-physical")
        print("REFUSED: FOUNDER ACTION: is for a physical step only (crew#281). This text names no "
              "device in his hand. Stage it instead: founder-blocker.py \"<action>\" --staged [N], and the "
              "API side is code, never a console.", file=sys.stderr)
        return 0
    tok, chat = ea._env("TELEGRAM_BOT_TOKEN"), ea._env("TELEGRAM_HOME_CHANNEL")
    if not tok or not chat:
        print("BLIND: TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL missing", file=sys.stderr)
        return 0
    if physical:
        outcome, key, text = "sent", "physical:" + action[:50], "FOUNDER ACTION: " + action.strip()
    else:
        minutes = staged_minutes or default_timeout()
        outcome, key, text = "staged", f"staged:{minutes}:" + action[:40], staged_text(action, minutes)
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
    telegram_ledger.record(SOURCE, outcome, text, key=key, msg_id=mid)
    print(f"telegram message_id={mid} {pinned}")
    print(text.splitlines()[0] + (" — " + target if target else ""))
    return mid


def parse_argv(argv: list[str]) -> tuple[list[str], str, int | None, bool, str | None]:
    """(positional args, session, staged minutes, physical, register row or None). Exits 2 on an unknown flag: `--help`
    once went to Telegram as "STAGED: --help is ready" (msg 14081, 2026-08-26). A flag is never
    the founder's message."""
    sess, args, minutes, physical, register = "", [], None, False, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--session="):
            sess = a.split("=", 1)[1]
        elif a == "--session" and i + 1 < len(argv):
            sess = argv[i + 1]; i += 1
        elif a == "--physical":
            physical = True
        elif a.startswith("--register="):
            register = a.split("=", 1)[1]
        elif a == "--register" and i + 1 < len(argv):
            register = argv[i + 1]; i += 1
        elif a == "--staged":
            minutes = 0
            if i + 1 < len(argv) and argv[i + 1].isdigit():
                minutes = int(argv[i + 1]); i += 1
        elif a.startswith("-"):
            print(f"REFUSED: unknown flag {a!r}\n" + (__doc__ or ""), file=sys.stderr)
            sys.exit(2)
        else:
            args.append(a)
        i += 1
    return args, sess, minutes, physical, register


if __name__ == "__main__":
    args, sess, minutes, physical, register = parse_argv(sys.argv[1:])
    if not args:
        print(__doc__); sys.exit(2)
    sys.exit(0 if send(args[0], args[1] if len(args) > 1 else "", sess,
                       staged_minutes=minutes or None, physical=physical, register=register) else 1)
