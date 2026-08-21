#!/usr/bin/env python3
"""Serve the founder's board on a fixed local URL, so reading it needs no agent session.

The founder, 2026-08-21: "nagaing different agent sessionsis ehausintg" and "the sooner wecan
get fouder out of loop the btter". `com.founder.board` already rebuilds the page every hour on
its own. What it could not do was SHOW it: the page only reached him when a session happened to
be alive and published it, so the freshest board on the machine could be an hour of work behind
what he was looking at, and he had to ask.

This serves exactly one file, on 127.0.0.1 only, and it serves the file's OWN age in a banner --
a stale page that says it is stale is honest, and a page that cannot say so is a black box.

    http://127.0.0.1:8787/          the board
    http://127.0.0.1:8787/health    plain text, for a probe

One file, never a directory listing: ~/.claude/state holds other sessions' state and none of it
is his to read by accident.
"""
from __future__ import annotations

import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOARD = os.path.expanduser("~/.claude/state/founder-board.html")
PORT = int(os.environ.get("FOUNDER_BOARD_PORT", "8787"))
STALE_S = 90 * 60          # the builder runs hourly; 90 minutes means a build was MISSED


def _banner(age_s: float) -> bytes:
    mins = int(age_s / 60)
    stale = age_s > STALE_S
    bg, fg = ("#7f1d1d", "#fff") if stale else ("#14532d", "#fff")
    msg = (f"board is {mins} minutes old — the hourly builder has missed a run"
           if stale else f"measured {mins} minutes ago")
    return (f'<div style="font:14px/1.5 -apple-system,sans-serif;background:{bg};color:{fg};'
            f'padding:8px 16px">{msg} · rebuild: '
            f'<code>launchctl kickstart -k gui/$(id -u)/com.founder.board</code></div>'
            ).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # one line per request in launchd's log is noise
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        try:
            age = time.time() - os.stat(BOARD).st_mtime
        except OSError as e:
            # A missing board is a FINDING, not a 404 with no explanation.
            self._send(503, f"no board on disk at {BOARD}: {e}".encode(), "text/plain")
            return
        if path == "/health":
            self._send(200, f"ok age_s={int(age)} stale={age > STALE_S}\n".encode(), "text/plain")
            return
        if path not in ("/", "/index.html", "/founder-board.html"):
            self._send(404, b"this server serves one page: /\n", "text/plain")
            return
        try:
            with open(BOARD, "rb") as fh:
                html = fh.read()
        except OSError as e:
            self._send(503, f"board unreadable: {e}".encode(), "text/plain")
            return
        self._send(200, _banner(age) + html, "text/html; charset=utf-8")


def selftest() -> int:
    import threading
    import urllib.request
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    fails = []
    try:
        with urllib.request.urlopen(base + "/health", timeout=5) as r:
            body = r.read().decode()
        if "ok age_s=" not in body:
            fails.append(f"health said {body!r}")
    except Exception as e:                                  # noqa: BLE001 - a selftest reports
        fails.append(f"health raised {type(e).__name__}: {e}")
    try:
        urllib.request.urlopen(base + "/../../.env", timeout=5)
        fails.append("a path outside the one file was served")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            fails.append(f"escape attempt returned {e.code}, wanted 404")
    except Exception as e:                                  # noqa: BLE001
        fails.append(f"escape attempt raised {type(e).__name__}")
    srv.shutdown()
    if fails:
        print("selftest FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS: serves the board and nothing else.")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"founder board on http://127.0.0.1:{PORT}/ from {BOARD}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
