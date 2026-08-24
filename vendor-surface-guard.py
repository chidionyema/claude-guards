#!/usr/bin/env python3
"""Refuse to put a founder-facing page on a vendor surface when we already serve one.

THE MISTAKE THIS EXISTS FOR, 2026-08-24. The founder asked for a visual board because he
does not use the command line (LAW 31). A session built one and published it to
claude.ai as an Artifact. He opened the link and got a 404, and said:

    "look you sennt ne aa claud artifact returnnong 404, this i sstuped, we need to nove
     off claude and pbecone agnostic our own prcesses and tooling"
    "too nuch frictin, the bord os tied to your sessionn, anything we generate bust be
     persisted in our patfron, else iot ends upn the void"

Two laws broken at once, and the second is the expensive one:

  * LAW 34 / R8, no provider single point of failure. His only status surface was hosted
    by the vendor whose session produced it. When the session ends or the account is not
    the one in his browser, the page is a 404 and the work is gone.
  * LAW 39 / LAW 43, inventory before you build. `~/.claude/scripts/board_serve.py` was
    ALREADY running on this machine under launchd job com.founder.boardserve, serving
    http://127.0.0.1:8787/ from a file rebuilt hourly by com.founder.board. A
    session-independent local board existed. The session built a second one anyway.

THE CLASS, in one sentence: a deliverable the founder must read is created on a surface
he cannot reach without an agent session. Not "artifacts are bad" -- reading one, listing
them, or answering a comment on one costs nothing and is allowed. Publishing is what
creates the surface, so publishing is what this refuses.

WHERE THE PAGE GOES INSTEAD: add a collector to ~/.claude/scripts/founder_board.py. It
renders to ~/.claude/state/founder-board.html hourly and is served on 127.0.0.1:8787 with
its own age in the banner. It survives the session, the account and the network.

THE ESCAPE HATCH, because a guard that refuses correct work is an outage (LAW 38): put
  # vendor-surface-intended
anywhere in the description or title, and say in the reply why this page cannot live on
the local board. Publishing to share a page OUTSIDE the estate -- a buyer, an advisor, a
customer -- is exactly that case, and it is not what this guard is about.

    python3 ~/.claude/scripts/vendor-surface-guard.py --selftest
"""
from __future__ import annotations

import json
import sys

LOCAL_BOARD = "http://127.0.0.1:8787/"
OVERRIDE = "vendor-surface-intended"

# Actions that only READ an existing artifact. None of them create a surface the
# founder depends on, so none of them are this guard's business.
READ_ONLY = {
    "list", "read", "comments", "reply", "resolve", "watch", "unwatch",
    "status", "resume_replies", "list_assets", "read_asset",
}

MESSAGE = f"""BLOCKED by vendor-surface-guard: this publishes a founder-facing page to claude.ai.

  The founder already has a board that does not need you alive to be read:
      {LOCAL_BOARD}
  Built by   ~/.claude/scripts/founder_board.py  (launchd: com.founder.board, hourly)
  Served by  ~/.claude/scripts/board_serve.py    (launchd: com.founder.boardserve)

  Put the content there -- add a collector to founder_board.py -- so it persists in our
  own platform instead of a vendor's. Anything else ends up in the void when the session
  does, which is exactly what happened on 2026-08-24 when he opened an artifact link and
  got a 404.

  LAW 34 / R8: no provider single point of failure, Claude included.
  LAW 39: the local board already existed. Building a second one is the mistake.

  If this page genuinely must be published outside the estate -- a buyer, an advisor, a
  customer -- put  # {OVERRIDE}  in the description or title and say why in your reply."""


def verdict(payload: dict) -> str | None:
    """Return the refusal text, or None to let the call through."""
    if payload.get("tool_name") != "Artifact":
        return None
    ti = payload.get("tool_input") or {}
    action = str(ti.get("action") or "publish").strip().lower()
    if action in READ_ONLY:
        return None
    haystack = " ".join(str(ti.get(k, "")) for k in ("description", "title", "label", "file_path"))
    if OVERRIDE in haystack:
        return None
    return MESSAGE


def selftest() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        if not cond:
            print(f"FAIL: {name}")
            ok = False

    def call(**ti):
        return verdict({"tool_name": "Artifact", "tool_input": ti})

    # It refuses.
    check("a bare publish is refused", call(file_path="/tmp/board.html") is not None)
    check("an explicit publish is refused",
          call(action="publish", file_path="/tmp/board.html") is not None)
    check("an update to an existing artifact is refused",
          call(file_path="/tmp/b.html", url="https://claude.ai/code/artifact/x") is not None)
    check("the refusal names the local board", LOCAL_BOARD in (call(file_path="/tmp/b.html") or ""))

    # It permits. A guard only ever seen refusing has never been shown to permit.
    check("reading an artifact is allowed",
          call(action="read", url="https://claude.ai/code/artifact/x") is None)
    check("listing artifacts is allowed", call(action="list") is None)
    check("replying to a comment is allowed",
          call(action="reply", url="u", thread_id="t", text="hi") is None)
    check("the override in the description permits a publish",
          call(file_path="/tmp/b.html",
               description=f"pitch page for the buyer # {OVERRIDE}") is None)
    check("the override in the title permits a publish",
          call(file_path="/tmp/b.html", title=f"Buyer pitch # {OVERRIDE}") is None)
    check("another tool is not this guard's business",
          verdict({"tool_name": "Write", "tool_input": {"file_path": "/tmp/x"}}) is None)

    print("PASS: it refuses a publish and permits a read." if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # fail open, always
    reason = verdict(payload)
    if reason:
        sys.stderr.write(reason + "\n")
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)  # fail open
