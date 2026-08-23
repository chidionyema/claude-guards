#!/usr/bin/env python3
"""Prove the estate can still reach the founder's phone.

Telegram is his entire interface: he works from the phone, not the laptop, so a
dead bot token or a broken route to his chat is a silent total outage — every
alert from maestro, The Architect and the guards would land in a log he never
reads. Measured 2026-08-23: The Architect was deaf for 31.5 hours once already
because the old estate held the poll, and nothing was checking delivery.

Two probes, because they fail differently (LAW 15):
  getMe            — the token is alive and names the bot we think it is.
  sendChatAction   — the route to the founder's chat works, without putting a
                     visible message on his phone. "typing" flickers and is gone.

The token is read from The Architect's .env, the same file maestro borrows from,
and is never printed, logged or passed on a command line.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ENV_PATH = Path(os.getenv("ARCHITECT_HOME", "~/dev/code/hermes-v2")).expanduser() / ".env"


def read_env(key: str) -> str:
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == key:
                return value.strip().strip("'\"")
    except OSError:
        return ""
    return ""


def call(token: str, method: str, params: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def main() -> int:
    token = read_env("TELEGRAM_BOT_TOKEN")
    chat_id = read_env("TELEGRAM_HOME_CHANNEL")
    if not token or not chat_id:
        print(f"FAIL: no token or chat id readable at {ENV_PATH}")
        return 1

    try:
        me = call(token, "getMe", {})
    except Exception as e:
        print(f"FAIL: getMe did not answer: {type(e).__name__}")
        return 1
    if not me.get("ok"):
        print("FAIL: getMe answered but the token is not accepted")
        return 1
    bot = me["result"].get("username", "?")

    try:
        action = call(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception as e:
        print(f"FAIL: token alive (@{bot}) but the chat is unreachable: {type(e).__name__}")
        return 1
    if not action.get("ok"):
        print(f"FAIL: token alive (@{bot}) but sendChatAction was refused")
        return 1

    print(f"PASS: @{bot} authenticates and the founder's chat accepts a chat action")
    return 0


if __name__ == "__main__":
    sys.exit(main())
