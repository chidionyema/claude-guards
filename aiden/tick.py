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
import signal
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
    # The exit code is NOT the send result. Measured 2026-08-23: under launchd the CLI
    # cannot read ~/.hermes/config.yaml (EPERM, the old dead estate), prints a config
    # warning, falls back to defaults, DELIVERS THE MESSAGE, and still exits 1. Every
    # tick since 17:58 recorded "delivery failed" for sends that may well have arrived,
    # and the founder read a silent estate as a quiet one.
    #
    # LAW 28: prove the arrival, not the send. The CLI already returns a message_id --
    # that is a receipt from Telegram's side, and it is the only thing here that says a
    # human could have seen this. Judge on it.
    out = (p.stdout or "").strip()
    body = None
    for line in (out, out[out.find("{"):] if "{" in out else ""):
        try:
            body = json.loads(line)
            break
        except (ValueError, TypeError):
            continue
    if isinstance(body, dict) and "success" in body:
        return {"ok": bool(body.get("success")) and bool(body.get("message_id")),
                "rc": p.returncode,
                "message_id": body.get("message_id"),
                "chat_id": body.get("chat_id"),
                "out": "" if body.get("success") else out[:400]}
    # No parseable receipt. An unparsed stdout is not a delivery, whatever the exit code.
    return {"ok": False, "rc": p.returncode, "message_id": None,
            "why": "the CLI printed no receipt",
            "out": (out or p.stderr or "").strip()[:400]}


#: A tick that never finishes is the worst of the three outcomes, because it
#: looks the same as an estate with nothing wrong. On 2026-08-23 one tick sat
#: 46 minutes inside a job scheduled every 5, with 26 seconds of CPU, while the
#: last receipt on disk read "nothing needed a person" and was two hours old.
#: Silence has to mean checked-and-clean, never still-walking-the-disk, so a tick
#: that overruns kills itself and writes a receipt saying it did.
DEADLINE_SECONDS = 240
LOCK = os.path.join(HOME, ".claude", "state", "aiden-tick.lock")


def _drop_lock():
    """Release the lock, and say so on the board if it cannot be released.

    This is the single act whose silent failure stops every FUTURE tick rather than
    this one, so it is the last place in the file that should swallow an error.
    """
    try:
        os.unlink(LOCK)
    except FileNotFoundError:
        pass
    except OSError as exc:
        # Use the estate's own reporter rather than a second hand-rolled board write:
        # one writer means one format, and it already handles its own failure.
        sys.path.append(os.path.join(HOME, ".claude", "scripts"))
        import guard_report
        guard_report.broken(__file__, 116,
                            f"cannot release {LOCK}: {type(exc).__name__}: {exc}. "
                            "Every later tick refuses to start until it is deleted.")


def _receipt(row):
    with open(RECEIPTS, "a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row))


def _guard(started):
    """Refuse to start on top of a tick that is still going, and bound this one."""
    try:
        prev = int(open(LOCK).read().strip())
    except (OSError, ValueError):
        prev = 0
    if prev:
        try:
            os.kill(prev, 0)
        except OSError:
            pass                      # it died without cleaning up; the lock is stale
        else:
            _receipt({"at": started, "alerts": None, "sent": 0,
                      "delivery": {"ok": False, "why": f"tick {prev} is still running"},
                      "board": BOARD})
            return False
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))

    def expired(_sig, _frm):
        _receipt({"at": started, "alerts": None, "sent": 0,
                  "delivery": {"ok": False,
                               "why": f"gave up after {DEADLINE_SECONDS}s walking the disk"},
                  "board": BOARD})
        # os._exit skips every cleanup path, so the lock this tick took would outlive it.
        # A stale lock only clears when the pid it names is dead AND unrecycled; until then
        # every later tick refuses to start and the estate is watched by nothing.
        _drop_lock()
        os._exit(1)
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(DEADLINE_SECONDS)
    return True


def main():
    now = time.time()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    if not _guard(started):
        return 1
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

    signal.alarm(0)
    _receipt({"at": started, "alerts": len(alerts), "sent": len(fresh),
              "delivery": result, "board": BOARD,
              "took_s": round(time.time() - now, 1)})
    _drop_lock()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
