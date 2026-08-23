#!/usr/bin/env python3
"""One tick of Aiden. Refresh the board, and deliver only what a person should read.

Two rules the estate paid for.

LAW 31: the founder does not run scripts, so the state has to be somewhere he is
already looking. The board file is rewritten every tick whether anything is wrong
or not, which is what makes silence readable: a stale timestamp on the page says
the watcher died, and no alert at all says the estate is fine. Those two look
identical if the only output is an alert.

LAW 28: an instrument nobody reads is not an instrument, and a `sent` with
nothing on the other end is the failure it is made of. Delivery here goes
through `hermes send`, which is the channel the founder already uses, and the
send result is recorded rather than assumed. Nothing new is subscribed to and no
second bot is created.

The same alert is sent once. A watcher that repeats itself every five minutes
teaches a person to mute it, and a muted channel is a channel that is not read.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
HERE = os.path.join(HOME, ".claude", "scripts", "aiden")
BOARD = os.path.join(HOME, ".claude", "state", "aiden-board.html")
SENT = os.path.join(HOME, ".claude", "state", "aiden-sent.json")
RECEIPTS = os.path.join(HOME, ".claude", "state", "aiden-ticks.jsonl")
HERMES = os.path.join(HOME, "dev", "code", "hermes-v2", ".venv", "bin", "python")

#: How long an alert stays "already said". Long enough that a slow-moving
#: problem is not repeated every five minutes, short enough that one still
#: unfixed tomorrow is raised again.
QUIET_SECONDS = 6 * 3600

_spec = importlib.util.spec_from_file_location("aiden", os.path.join(HERE, "aiden.py"))
aiden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aiden)


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def deliver(text):
    """Send through the channel that already exists. Returns what actually happened."""
    if not os.path.exists(HERMES):
        return {"ok": False, "why": "hermes venv is not on this machine"}
    try:
        p = subprocess.run(
            [HERMES, "-m", "hermes_cli.main", "send", "--to", "telegram",
             "--subject", "Aiden", "--json", text],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "why": f"{type(e).__name__}: {e}"}
    return {"ok": p.returncode == 0, "rc": p.returncode,
            "out": (p.stdout or p.stderr or "").strip()[:400]}


def main():
    now = time.time()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    aiden.html(BOARD, 24)
    alerts = aiden.alerts(24)

    seen = {k: v for k, v in load(SENT, {}).items() if now - v < QUIET_SECONDS}
    fresh = []
    for a in alerts:
        #: Fingerprint the alert without its changing numbers, so "waiting 12 min"
        #: and "waiting 40 min" are one alert and not two.
        key = hashlib.sha256(
            "".join(c for c in a if not c.isdigit()).encode()).hexdigest()[:16]
        if key in seen:
            continue
        seen[key] = now
        fresh.append(a)

    result = {"ok": True, "why": "nothing needed a person"}
    if fresh:
        result = deliver("\n".join(fresh[:12]))
    with open(SENT, "w") as f:
        json.dump(seen, f)

    receipt = {"at": started, "alerts": len(alerts), "sent": len(fresh),
               "delivery": result, "board": BOARD}
    with open(RECEIPTS, "a") as f:
        f.write(json.dumps(receipt) + "\n")
    print(json.dumps(receipt))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
