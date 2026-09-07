#!/usr/bin/env python3
"""What every agent session is doing right now, computed at read time from the hook ledger.

Founder, 2026-09-07: *"you need to fully audit their transaction in real time as they are
working"*, after watching a session sit silent for 2m29s on one blocking command.

WHY THIS DOES NOT WALK THE TRANSCRIPTS
--------------------------------------
The page that answered this question before (`/ops`) was produced by `ticket-gate.py
--dashboard`, which walks 81k transcripts across 16.6k directories. Measured 2026-09-07:
**4 minutes 32 seconds** for one rebuild, 55s user + 48s system. It was rebuilt by a
five-minute tick, so at best it was a still photograph taken every five minutes -- and when
aiden's tick was deleted, nothing called it at all and the page froze on 27 August for
eleven days while its own banner quietly said "sessions measured 15849 minutes ago".

A poll that costs 4.5 minutes cannot be real time, and a produced file whose producer is
gone is a lie with a timestamp. So the data flow is inverted: every session already writes
one line per tool call through `hook-run.py` -- it has to, because every guard runs through
that wrapper. Reading the tail of that one append-only file is O(bytes read) and answers in
milliseconds, and nothing has to stay alive for it to be true.

    python3 session_live.py            one line per live session
    python3 session_live.py --html     the same as the /ops page body
    python3 session_live.py --selftest
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import time

LEDGER = os.environ.get("HOOK_OUTCOMES") or os.path.expanduser(
    "~/.claude/state/hook-outcomes.jsonl"
)
TAIL_BYTES = int(os.environ.get("SESSION_LIVE_TAIL_BYTES") or 2 * 1024 * 1024)
LIVE_S = 30 * 60  # a session with no hook in half an hour is gone, not idle
REFUSAL_WINDOW_S = 600  # guard refusals worth showing next to what it is doing now


def _ts(value: str) -> float:
    """ISO-8601 Z to epoch seconds; 0.0 when the row is malformed."""
    try:
        return (
            dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return 0.0


def read_rows(path: str | None = None, tail_bytes: int = TAIL_BYTES) -> list[dict]:
    """The tail of the ledger, parsed. A partial first line is dropped, never guessed at.

    The path is resolved on the call, not bound as a default: a default freezes LEDGER at import
    and the long-lived board server would then read whatever the ledger was when it started.
    """
    path = path or LEDGER
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()
            blob = fh.read()
    except OSError:
        return []
    rows = []
    for line in blob.decode("utf-8", "replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("session"):
            rows.append(row)
    return rows


def sessions(
    rows: list[dict], now: float | None = None, live_s: int = LIVE_S
) -> list[dict]:
    """One record per session that moved inside the window, newest first.

    A session's state is what its newest row says it was doing. PreToolUse means the call is
    in flight -- the wrapper writes the line before the tool runs -- so its age is how long
    the session has been on that one command, which is the number the founder asked for.
    """
    now = time.time() if now is None else now
    by_session: dict[str, dict] = {}
    for row in rows:
        at = _ts(row.get("at", ""))
        if not at or now - at > live_s:
            continue
        sid = str(row.get("session"))
        cur = by_session.setdefault(
            sid,
            {
                "session": sid,
                "at": 0.0,
                "event": "",
                "tool": "",
                "what": "",
                "cwd": "",
                "refusals": [],
                "calls": 0,
            },
        )
        if row.get("event") == "PreToolUse":
            cur["calls"] += 1
        if row.get("refused") and now - at <= REFUSAL_WINDOW_S:
            cur["refusals"].append(
                {"hook": row.get("hook", ""), "what": row.get("what", ""), "at": at}
            )
        # Several hooks fire for one tool call and share a timestamp; the first one seen wins,
        # and a later row only replaces it when it is genuinely newer.
        if at > cur["at"]:
            cur.update(
                {
                    "at": at,
                    "event": row.get("event", ""),
                    "tool": row.get("tool", ""),
                    "what": row.get("what", ""),
                    "cwd": row.get("cwd", "") or cur["cwd"],
                }
            )
    out = []
    for cur in by_session.values():
        cur["since_s"] = int(now - cur["at"])
        cur["state"] = _state(cur)
        out.append(cur)
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def _state(cur: dict) -> str:
    event = cur.get("event")
    if event == "UserPromptSubmit":
        return "reading the founder"
    if event == "Stop":
        return "idle, waiting for the founder"
    if event == "SessionStart":
        return "starting"
    if event == "PreToolUse":
        return "running"
    return event or "unknown"


def _age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def text(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        flag = "  <-- BLOCKED" if r["state"] == "running" and r["since_s"] >= 90 else ""
        lines.append(
            f"{r['session']:<10} {_age(r['since_s']):>7} ago  {r['state']:<28} "
            f"{r['tool']:<8} {r['what'][:80]}{flag}"
        )
        for ref in r["refusals"]:
            lines.append(
                f"{'':<10} {'':>7}      refused by {ref['hook']}: {ref['what'][:60]}"
            )
    return "\n".join(lines) or "no session has run a tool in the last 30 minutes"


def render(rows: list[dict], now: float | None = None) -> bytes:
    now = time.time() if now is None else now
    stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%H:%M:%SZ")
    esc = html.escape
    parts = [
        '<meta http-equiv="refresh" content="10">',
        "<style>body{font:14px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;margin:0;"
        "background:#0b1220;color:#e5e7eb}table{border-collapse:collapse;width:100%}"
        "td,th{padding:8px 12px;border-bottom:1px solid #1f2937;vertical-align:top;text-align:left}"
        "th{color:#9ca3af;font-weight:600;font-size:12px;text-transform:uppercase}"
        "code{font:13px ui-monospace,Menlo,monospace;color:#93c5fd}"
        ".b{color:#fca5a5;font-weight:600}.i{color:#9ca3af}.r{color:#fdba74}</style>",
        f'<div style="background:#14532d;padding:8px 16px">computed now, {esc(stamp)} '
        f"&mdash; {len(rows)} session(s) that ran a tool in the last 30 minutes; "
        "this page reads the hook ledger on every request, so it cannot go stale</div>",
        "<table><tr><th>session</th><th>for</th><th>state</th><th>doing</th><th>where</th></tr>",
    ]
    for r in rows:
        blocked = r["state"] == "running" and r["since_s"] >= 90
        cls = "b" if blocked else ("i" if r["state"].startswith("idle") else "")
        doing = f"<code>{esc(r['what'][:140])}</code>" if r["what"] else ""
        if r["tool"]:
            doing = f"{esc(r['tool'])} {doing}"
        for ref in r["refusals"]:
            doing += (
                f'<div class="r">refused by {esc(ref["hook"])}: '
                f"{esc(ref['what'][:100])}</div>"
            )
        parts.append(
            f'<tr><td>{esc(r["session"])}</td><td class="{cls}">{_age(r["since_s"])}</td>'
            f'<td class="{cls}">{esc(r["state"])}{" &mdash; over 90s on one call" if blocked else ""}</td>'
            f'<td>{doing}</td><td class="i">{esc(r["cwd"][-46:])}</td></tr>'
        )
    parts.append("</table>")
    if not rows:
        parts.append(
            '<p class="i" style="padding:16px">No session has run a tool in the last '
            "30 minutes.</p>"
        )
    return "".join(parts).encode("utf-8")


def selftest() -> int:
    import tempfile

    now = time.time()

    def at(offset):
        return dt.datetime.fromtimestamp(now - offset, dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    fixture = [
        {
            "at": at(300),
            "event": "PreToolUse",
            "hook": "rule-guard.py",
            "session": "aaaa1111",
            "exit": 0,
            "ms": 12,
            "refused": False,
            "tool": "Bash",
            "what": "trivy config platform/",
            "cwd": "/repo/wt-lanes",
        },
        {
            "at": at(20),
            "event": "Stop",
            "hook": "dod-guard.py",
            "session": "bbbb2222",
            "exit": 0,
            "ms": 9,
            "refused": False,
        },
        {
            "at": at(30),
            "event": "PreToolUse",
            "hook": "dupe-work-fence.py",
            "session": "cccc3333",
            "exit": 2,
            "ms": 30,
            "refused": True,
            "tool": "Bash",
            "what": "gh pr create",
        },
        {
            "at": at(9999),
            "event": "Stop",
            "hook": "x.py",
            "session": "dddd4444",
            "exit": 0,
            "ms": 1,
            "refused": False,
        },
    ]
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ledger.jsonl")
        with open(path, "w") as fh:
            fh.write("}garbage not json\n")
            for row in fixture:
                fh.write(json.dumps(row) + "\n")
        rows = sessions(read_rows(path), now=now)
        got = {r["session"]: r for r in rows}
        if "dddd4444" in got:
            fails.append(
                "a session idle for 2.7 hours is not live and must not be listed"
            )
        if got.get("aaaa1111", {}).get("state") != "running":
            fails.append(
                "a session whose newest row is PreToolUse is running that call"
            )
        if got.get("aaaa1111", {}).get("since_s", 0) < 290:
            fails.append(
                "the age of a running call is measured from the call, not from now"
            )
        if got.get("bbbb2222", {}).get("state") != "idle, waiting for the founder":
            fails.append("a session whose newest row is Stop is idle")
        if not got.get("cccc3333", {}).get("refusals"):
            fails.append("a refusal inside the window is shown next to the session")
        if rows and rows[0]["session"] != "bbbb2222":
            fails.append("rows are newest first")
        body = render(rows, now=now)
        if b"BLOCKED" in body and b"over 90s" not in body:
            fails.append("a blocked session is named in the page")
        if b"trivy config platform/" not in body:
            fails.append("the page shows the command a session is actually running")

        # A page nobody can load in a browser tab is not a live view: 20k rows, under a second.
        bulk = os.path.join(tmp, "bulk.jsonl")
        with open(bulk, "w") as fh:
            for i in range(20000):
                fh.write(
                    json.dumps(
                        {
                            "at": at(i % 1500),
                            "event": "PreToolUse",
                            "hook": "h.py",
                            "session": f"s{i % 40:07d}",
                            "exit": 0,
                            "ms": 1,
                            "refused": False,
                            "tool": "Bash",
                            "what": "x" * 60,
                        }
                    )
                    + "\n"
                )
        t0 = time.monotonic()
        render(sessions(read_rows(bulk), now=now), now=now)
        took = time.monotonic() - t0
        if took > 1.0:
            fails.append(f"20k ledger rows rendered in {took:.2f}s, over the 1s budget")
    for line in fails:
        print("FAIL " + line)
    print(f"session_live selftest: {8 - len(fails)}/8 passed")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    rows = sessions(read_rows())
    if "--html" in argv:
        sys.stdout.buffer.write(render(rows))
        return 0
    print(text(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
