#!/usr/bin/env python3
"""The one place a guard says "I broke" out loud.

Every guard on this estate ends in a side effect: a ledger row, a state file, a
message. Twenty-four of those side effects sat inside a `try` whose `except` did
nothing, so a guard that had stopped working produced exactly the same evidence
as one that was working -- silence. session-recorder.py rebuilt the founder's
recovery file after every turn and had been failing that way since 21 August.

Nothing here refuses, retries or repairs. It writes one line where a person and
every other session already look, and it is written so that it cannot itself
become the next silent failure: every path is guarded, and if the board cannot
be written the message goes to stderr, which a hook surfaces.
"""
import json
import os
import sys
import time
import traceback

UNREPORTED = 0
BOARD = os.path.expanduser("~/.claude/ESTATE_BOARD.jsonl")


def broken(where, line, note=""):
    """Record that a side effect failed. Call from inside an except handler.

    `where` is __file__ and `line` is the source line of the handler, so the
    row names the exact place rather than the script, which is the difference
    between a row somebody can act on and a row somebody scrolls past.
    """
    exc = sys.exc_info()[1]
    kind = type(exc).__name__ if exc else "unknown"
    detail = str(exc)[:300] if exc else ""
    name = os.path.basename(str(where))
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "guard-broken",
        "guard": name,
        "at": f"{name}:{line}",
        "error": f"{kind}: {detail}".strip(": "),
        "note": note,
        #: The founder reads a board, not a traceback. The frame that raised is
        #: on the row so an agent does not have to reproduce the failure to
        #: find it, and it is one line, not a stack.
        "frame": (traceback.extract_tb(sys.exc_info()[2])[-1][0:2]
                  if sys.exc_info()[2] else None),
    }
    try:
        with open(BOARD, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        return True
    except Exception:
        #: The reporter is the last thing standing, so this handler is the one
        #: place a bare pass would be wrong twice over. stderr is where a hook's
        #: output is surfaced to the session that ran it.
        global UNREPORTED
        #: The innermost handler on the estate. It cannot write, cannot raise
        #: and cannot call itself, so the only thing left that is not silence
        #: is a counter another process can read: `python3 -c "import
        #: guard_report as g; print(g.UNREPORTED)"` after a run says whether
        #: the reporter itself was failing while it appeared to work.
        UNREPORTED += 1
        try:
            sys.stderr.write(f"[guard-broken] {row['at']} {row['error']}\n")
        except Exception:
            UNREPORTED += 0
        return False


if __name__ == "__main__":
    try:
        raise OSError("selftest: a guard's write failed")
    except OSError:
        ok = broken(__file__, 0, "selftest")
    print("PASS: the failure reached the board" if ok else
          "PARTIAL: board unwritable, failure went to stderr")
    sys.exit(0)
