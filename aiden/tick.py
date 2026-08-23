#!/usr/bin/env python3
"""One tick of Aiden. Refresh the board, and deliver only what a person should read.

Two rules the estate paid for.

LAW 31: the founder does not run scripts, so the state has to be somewhere he is
already looking. The board file is rewritten every tick whether anything is wrong
or not, which is what makes silence readable: a stale timestamp on the page says
the watcher died, and no alert at all says the estate is fine. Those two look
identical if the only output is an alert.

LAW 28: an instrument nobody reads is not an instrument, and a `sent` with
nothing on the other end is the failure it is made of. Delivery goes through
`estate_alert`, the estate's existing Telegram sender, which posts direct to the
API and hands back Telegram's own message_id. That id is the receipt, and it is
what the tick is judged on -- an exit code says only that a program ended.
Nothing new is subscribed to and no second bot is created.

The same alert is sent once. A watcher that repeats itself every five minutes
teaches a person to mute it, and a muted channel is a channel that is not read.
"""
import hashlib
import importlib.util
import json
import os
import signal
import sys
import time

HOME = os.path.expanduser("~")
HERE = os.path.join(HOME, ".claude", "scripts", "aiden")
BOARD = os.path.join(HOME, ".claude", "state", "aiden-board.html")
SENT = os.path.join(HOME, ".claude", "state", "aiden-sent.json")
RECEIPTS = os.path.join(HOME, ".claude", "state", "aiden-ticks.jsonl")

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
    """Send through the estate's own sender. Returns what actually happened.

    NOT the hermes CLI, and the reason is measured. `~/.hermes` is a symlink into
    `~/Documents`, which macOS TCC hides from a LaunchAgent, so under launchd that CLI
    could not read its own config, fell back to a credential-free default, and the send
    genuinely failed -- exit 1, no message_id.

    Counted, not assumed. Of the 32 cycles logged on 2026-08-23, 3 reached this send
    and it failed (17:58:29Z, 19:00:32Z, 19:50:33Z), and 1 reached it and succeeded
    (19:30:05Z, message 12892). So the old path was intermittent, not dead. The larger
    share of the founder's silence was a different fault in the same window: 12 cycles
    were killed at 240s while walking the transcript tree, and never got as far as
    sending. That one is fixed in observe.py, by walking once per process instead of
    twice. Both were repaired in the same commit, which is exactly the shape LAW 29
    warns about -- two faults in one window read as one cause unless you count them.

    The estate already left that path on 2026-08-22, for this same TCC denial, when
    com.founder.estatepush failed on schedule and passed by hand. `estate_alert` posts
    straight to api.telegram.org and reads its token from `~/.config/estate/estate.env`,
    which is outside `~/Documents` and readable under launchd. Aiden was the one job
    still routing through the dead tree.

    LAW 28: judge on Telegram's own message_id, never on an exit code.
    """
    sys.path.append(os.path.join(HOME, ".claude", "scripts"))
    try:
        from estate import estate_alert
    except Exception as e:                        # noqa: BLE001 - never crash a tick
        return {"ok": False, "why": f"estate_alert will not import: {type(e).__name__}: {e}"}
    try:
        # No debounce_key. Aiden already deduplicates in aiden-sent.json over
        # QUIET_SECONDS, and a second suppressor underneath it would silently drop the
        # alerts this tick had just judged fresh.
        msg_id = estate_alert.send_operator_alert(text)
    except Exception as e:                        # noqa: BLE001 - never crash a tick
        return {"ok": False, "why": f"{type(e).__name__}: {e}"}
    return {"ok": bool(msg_id), "message_id": int(msg_id or 0),
            "why": "" if msg_id else "telegram returned no message_id"}


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
    fresh, in_this_tick = [], set()
    for a in alerts:
        #: Fingerprint the alert without its changing numbers, so "waiting 12 min"
        #: and "waiting 40 min" are one alert and not two.
        key = hashlib.sha256(
            "".join(c for c in a if not c.isdigit()).encode()).hexdigest()[:16]
        #: Both sets, and they are not the same question. `seen` is what was said in
        #: the last six hours. `in_this_tick` is what this one message already says,
        #: and it is needed because nine sessions parked in the same temp directory
        #: produce nine alert lines that differ only in a minute count. Measured
        #: 2026-08-23, message 12903 went out carrying that exact page: one real
        #: line and eight copies of it.
        if key in seen or key in in_this_tick:
            continue
        in_this_tick.add(key)
        fresh.append((key, a))

    #: Only what actually goes out. Marking an alert said before knowing whether it
    #: arrived is how a broken channel silences itself: measured 2026-08-23, five
    #: fingerprints sat in aiden-sent.json holding real alerts quiet for six hours
    #: apiece, every one of them from a tick whose delivery had failed. An alert is
    #: "already said" when Telegram has given back a message id, and not before.
    #: The cap is here for the same reason -- alerts past it were never sent, so they
    #: must stay sayable on the next tick.
    result = {"ok": True, "why": "nothing needed a person"}
    if fresh:
        going = fresh[:12]
        result = deliver("\n".join(a for _, a in going))
        if result.get("ok"):
            for key, _ in going:
                seen[key] = now
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
