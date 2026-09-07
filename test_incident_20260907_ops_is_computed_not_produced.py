"""The /ops page is computed on the request, so it cannot freeze again.

Incident 2026-09-07. The founder asked to see what his sessions were doing while they worked.
/ops answered with a page written on 27 August: it was produced by `ticket-gate.py --dashboard`
on aiden's five-minute tick, aiden's job had been removed, and nothing else ever called the
producer. The page carried its own age in a banner -- "sessions measured 15849 minutes ago" --
and served eleven-day-old sessions underneath it for eleven days.

Measured the same day: one rebuild of that page took 4 minutes 32 seconds, because it walked
81k transcripts across 16.6k directories. A five-minute tick could not have kept up with it
even while it was alive.

These tests hold the shape that replaced it: the page is rendered from the hook ledger on the
request that asks for it, by session_live.py, in milliseconds.
"""

import json
import os
import sys
import tempfile
import threading
import time
from http.client import HTTPConnection
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def check(ok, why):
    """Raise on a failed expectation. Plain `assert` is stripped by `python -O`, so a test that
    matters is not allowed to depend on it (estate Python standard, crew#620 row 1)."""
    if not ok:
        raise AssertionError(why)


def _ledger(tmp: str, rows: list[dict]) -> str:
    path = os.path.join(tmp, "hook-outcomes.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def _at(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def test_the_page_shows_a_call_that_is_running_right_now():
    """A session that started a command four minutes ago is on that command, and the page says so
    with the command in it -- which is the question the founder asked."""
    import session_live

    with tempfile.TemporaryDirectory() as tmp:
        path = _ledger(
            tmp,
            [
                {
                    "at": _at(240),
                    "event": "PreToolUse",
                    "hook": "rule-guard.py",
                    "session": "abcd1234",
                    "exit": 0,
                    "ms": 4,
                    "refused": False,
                    "tool": "Bash",
                    "what": "trivy config platform/",
                    "cwd": "/repo/wt-lanes",
                }
            ],
        )
        rows = session_live.sessions(session_live.read_rows(path))
        check(
            [r["session"] for r in rows] == ["abcd1234"],
            "one session, the one that ran",
        )
        check(
            rows[0]["state"] == "running", f"state was {rows[0]['state']}, not running"
        )
        check(235 <= rows[0]["since_s"] <= 300, "the age of the call is wrong")
        page = session_live.render(rows).decode()
        check(
            "trivy config platform/" in page,
            "the page does not name the running command",
        )


def test_the_served_page_reads_the_ledger_on_every_request():
    """The proof that it cannot go stale: append to the ledger between two requests to the SAME
    running server, and the second response carries what the first could not have known."""
    import session_live

    with tempfile.TemporaryDirectory() as tmp:
        path = _ledger(
            tmp,
            [
                {
                    "at": _at(5),
                    "event": "PreToolUse",
                    "hook": "h.py",
                    "session": "first111",
                    "exit": 0,
                    "ms": 1,
                    "refused": False,
                    "tool": "Bash",
                    "what": "the first command",
                }
            ],
        )
        os.environ["HOOK_OUTCOMES"] = path
        session_live.LEDGER = path
        import board_serve

        srv = ThreadingHTTPServer(("127.0.0.1", 0), board_serve.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def fetch():
            conn = HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/ops")
            body = conn.getresponse().read().decode()
            conn.close()
            return body

        try:
            first = fetch()
            check("the first command" in first, "the first request missed a live row")
            check(
                "the second command" not in first, "saw a row written after the request"
            )
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "at": _at(0),
                            "event": "PreToolUse",
                            "hook": "h.py",
                            "session": "second22",
                            "exit": 0,
                            "ms": 1,
                            "refused": False,
                            "tool": "Bash",
                            "what": "the second command",
                        }
                    )
                    + "\n"
                )
            second = fetch()
            check("the second command" in second, "the page did not re-read the ledger")
        finally:
            srv.shutdown()
            os.environ.pop("HOOK_OUTCOMES", None)


def test_a_page_load_costs_milliseconds_not_minutes():
    """The producer this replaced took 272 seconds. A live page has to answer inside a request."""
    import session_live

    with tempfile.TemporaryDirectory() as tmp:
        rows = [
            {
                "at": _at(i % 900),
                "event": "PreToolUse",
                "hook": "h.py",
                "session": f"s{i % 30:07d}",
                "exit": 0,
                "ms": 1,
                "refused": False,
                "tool": "Bash",
                "what": "x" * 80,
            }
            for i in range(20000)
        ]
        path = _ledger(tmp, rows)
        t0 = time.monotonic()
        session_live.render(session_live.sessions(session_live.read_rows(path)))
        check(
            time.monotonic() - t0 < 1.0, "20k ledger rows took over a second to render"
        )


def test_the_hook_wrapper_records_what_the_session_is_doing():
    """The ledger is only a live audit if the line says which tool and which command. hook-run
    writes that line before the tool runs, for every session, and it is where the page reads."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_run",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook-run.py"),
    )
    hook_run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook_run)
    bash = hook_run.doing(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git  push", "description": "d"},
        }
    )
    check(bash == ("Bash", "git push"), f"a Bash call reads as {bash}")
    edit = hook_run.doing({"tool_name": "Edit", "tool_input": {"file_path": "/a/b.py"}})
    check(edit == ("Edit", "/a/b.py"), f"an Edit call reads as {edit}")
    check(hook_run.doing({}) == ("", ""), "an empty payload should read as nothing")
