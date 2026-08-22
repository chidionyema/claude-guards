#!/usr/bin/env python3
"""Incident test: a failed boot must not kill the bridge's worker thread.

2026-08-22. The Mac lost its route while ai.estate.kimi-bridge was relaunching.
Bridge.run() called start() unguarded, page.goto raised
ERR_INTERNET_DISCONNECTED, and the worker thread died. The process kept its
listener open, so launchd's KeepAlive never fired and /health answered
"starting" for hours while every query sat on the queue with nobody to take it.

Two rules, both asserted here:
  1. A start() that raises leaves the worker alive and the state "down".
  2. Once start() stops raising, the worker boots itself without a query.

Run: /Users/chidionyema/.kimi-bridge/venv/bin/python test_kimi_bridge_boot.py
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="kimi-boot-test-")
os.environ["BRIDGE_HOME"] = TMP
os.environ["BRIDGE_PORT"] = "8799"          # never bound; no server is started
sys.path.insert(0, str(Path(__file__).resolve().parent))
(Path(TMP) / "logs").mkdir(parents=True, exist_ok=True)

import kimi_bridge as kb

kb.HEALTH_EVERY = 1                          # do not wait a minute for the retry


def make_bridge(fail_times):
    """A Bridge whose start() raises the first `fail_times` calls."""
    b = kb.Bridge.__new__(kb.Bridge)
    b.jobs = kb.queue.Queue()
    b.con = kb.db()
    b.page = b.ctx = b.pw = None
    b.state, b.detail = "starting", ""
    b.last_ok = b.last_used = 0.0
    b.captured = []
    b.calls = 0

    def start():
        b.calls += 1
        if b.calls <= fail_times:
            raise RuntimeError("net::ERR_INTERNET_DISCONNECTED")
        b.page = object()                    # a browser, as far as run() cares
        b.state, b.detail = "healthy", "signed in, composer present"

    b.start = start
    b.stop = lambda: None
    b.refresh_health = lambda: b.state
    b.park = lambda: None
    return b


# The third test kills a thread on purpose. Its traceback is the expected
# result, not a failure, so keep it off the screen.
threading.excepthook = lambda a: None


def run_for(b, seconds):
    t = threading.Thread(target=b.run, daemon=True)
    t.start()
    time.sleep(seconds)
    return t


def test_boot_failure_does_not_kill_the_worker():
    b = make_bridge(fail_times=10**6)        # the network never comes back
    t = run_for(b, 1.0)
    assert t.is_alive(), "the worker thread died on a failed boot"
    assert b.state == "down", f"state should be down, got {b.state!r}"
    assert b.page is None
    print("PASS  boot failure keeps the worker alive and reports down")


def test_worker_boots_itself_once_the_network_returns():
    b = make_bridge(fail_times=1)            # one outage, then the route is back
    # jobs.get() blocks 5s, so the idle branch that carries the retry cannot
    # run sooner than that however small HEALTH_EVERY is. Wait past one turn.
    t = run_for(b, 8.0)
    assert t.is_alive(), "the worker thread died"
    assert b.state == "healthy", f"never recovered; state {b.state!r}, detail {b.detail!r}"
    assert b.calls >= 2, "the loop never retried the boot"
    print(f"PASS  self-healed with no query after {b.calls} start attempts")


def test_the_old_code_would_have_failed_this():
    """The bug, reproduced: an unguarded start() takes the thread with it."""
    b = make_bridge(fail_times=10**6)
    dead = []

    def old_run():
        try:
            b.start()                        # what run() used to do, bare
        except Exception:
            dead.append(True)
            raise

    t = threading.Thread(target=old_run, daemon=True)
    t.start()
    t.join(2)
    assert dead, "the reproduction did not reproduce"
    assert not t.is_alive(), "the old shape was supposed to die here"
    print("PASS  the pre-fix shape dies, which is the bug this test guards")


if __name__ == "__main__":
    test_the_old_code_would_have_failed_this()
    test_boot_failure_does_not_kill_the_worker()
    test_worker_boots_itself_once_the_network_returns()
    print("\n3/3 green")
