#!/usr/bin/env python3
"""feed-guard: every session writes a six-line handoff to ~/.estate/feed.md every 30 minutes.

Founder, 2026-08-25 (R33): "every 30 minutes ... even if agent sessions die, we can recover
easily." A dead session has left its last state in the feed; "Status" is answered from it.

Hooks: Stop blocks the turn once when this session's entry is older than 30 minutes or absent;
SessionStart injects the last entries; UserPromptSubmit reminds when overdue.
Commands: append --session ID --lane NAME (shape is policy/feed.rego: 8 lines max, 🔴 🟡 🟢 ⚪
🔧 🔀 📍 marks, TOUCHES and OVERLAP required); status [--n 5]; selftest (both ways, temp feed).
Residual: Stop fires only at turn end, so a 90-minute turn appends late; a session that never
stops is reached by no hook. Without opa the shape check is BLIND, never a verdict.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FEED = Path(os.environ.get("ESTATE_FEED") or os.path.expanduser("~/.estate/feed.md"))
INTERVAL_S = 30 * 60
# The handoff shape is policy/feed.rego (crew#259); this file only asks OPA about it.
POLICY = Path(__file__).resolve().parent / "policy"
HEAD = re.compile(r"^## (\S+) · session (\S+) · lane (.*)$")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def entries(feed: Path) -> list[tuple[dt.datetime, str, str, list[str]]]:
    out = []
    if not feed.is_file():
        return out
    cur = None
    for ln in feed.read_text(encoding="utf-8", errors="replace").splitlines():
        m = HEAD.match(ln)
        if m:
            cur = (dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")), m.group(2), m.group(3), [])
            out.append(cur)
        elif cur and ln.strip():
            cur[3].append(ln)
    return out


def last_for(feed: Path, session: str):
    mine = [e for e in entries(feed) if e[1] == session]
    return mine[-1] if mine else None


def overdue(feed: Path, session: str, at: dt.datetime | None = None) -> int | None:
    """Seconds since this session's last entry, or None when it has one inside the interval."""
    at = at or now()
    e = last_for(feed, session)
    if e is None:
        return -1
    age = int((at - e[0]).total_seconds())
    return age if age >= INTERVAL_S else None


def append(feed: Path, session: str, lane: str, body: str, at: dt.datetime | None = None) -> str | None:
    lines = [l.rstrip() for l in body.strip().splitlines() if l.strip()]
    denied = denials(lines)
    if denied:
        return "; ".join(denied)
    at = at or now()
    feed.parent.mkdir(parents=True, exist_ok=True)
    with feed.open("a", encoding="utf-8") as fh:
        if feed.stat().st_size == 0:
            fh.write("# Estate feed\n\nOne handoff per session per 30 minutes (R33). Newest at the bottom. "
                     "Written by `python3 ~/.claude/scripts/feed-guard.py append`; read with `status`.\n\n")
        fh.write(f"## {at.strftime('%Y-%m-%dT%H:%M:%SZ')} · session {session} · lane {lane}\n" + "\n".join(lines) + "\n\n")
    return None


def denials(lines: list[str]) -> list[str]:
    opa = shutil.which("opa")  # the shape lives in policy/feed.rego; this decides nothing itself
    if not opa:
        return ["BLIND: opa is not installed, the handoff shape was not checked"]
    out = subprocess.run([opa, "eval", "--format", "json", "--ignore", "fixtures", "--ignore", "*.json",
                          "--data", str(POLICY), "--stdin-input", "data.feed.deny"],
                         input=json.dumps({"lines": lines}), capture_output=True, text=True, timeout=10)
    if out.returncode != 0:
        return ["BLIND: opa eval failed: " + out.stderr.strip()[:120]]
    return sorted(json.loads(out.stdout)["result"][0]["expressions"][0]["value"])


def block_text(session: str, lane: str, age: int) -> str:
    why = "has no entry in the feed" if age < 0 else f"last wrote to the feed {age // 60} min ago"
    return (f"FEED GUARD (R33): this session {why}; the limit is 30 minutes. Append the handoff now, "
            f"then end the turn:\n"
            f"python3 ~/.claude/scripts/feed-guard.py append --session {session} --lane {lane} <<'EOF'\n"
            f"🔴 Blocked: <what, who unblocks>\n🟡 Active: <issue numbers>\n🟢 Done: <merged, with sha>\n"
            f"⚪ Pending: <founder pick>\n🔧 TOUCHES: <files, services, ports, secrets you will change in 2h, or none>\n"
            f"🔀 OVERLAP: <issue numbers another session also touches, or none>\n📍 State: <file or URL>\nEOF\n"
            f"Eight lines at most; TOUCHES and OVERLAP are required (crew#259, policy/feed.rego).")


def hook(kind: str) -> int:
    try: payload = json.load(sys.stdin)
    except Exception: payload = {}
    session = (payload.get("session_id") or "unknown")[:8]
    lane = Path(payload.get("cwd") or os.getcwd()).name
    if kind == "SessionStart":
        tail = entries(FEED)[-6:]
        if tail:
            body = "\n".join(f"## {e[0].strftime('%Y-%m-%dT%H:%MZ')} · {e[1]} · {e[2]}\n" + "\n".join(e[3]) for e in tail)
            print(f"[feed] LAST {len(tail)} HANDOFFS FROM {FEED} (R33). When the founder says 'Status', summarise these; "
                  f"do not re-measure what they answer.\n{body}")
        print(f"[feed] You write a 6-line handoff here every 30 minutes: python3 ~/.claude/scripts/feed-guard.py append --session {session} --lane {lane}")
        return 0
    age = overdue(FEED, session)
    if age is None or (kind == "Stop" and payload.get("stop_hook_active")):
        return 0
    if kind == "Stop":
        print(json.dumps({"decision": "block", "reason": block_text(session, lane, age)}))
        return 0
    print(f"[feed] handoff overdue ({'none yet' if age < 0 else f'{age // 60} min'}); append one before this turn ends: "
          f"python3 ~/.claude/scripts/feed-guard.py append --session {session} --lane {lane}")
    return 0


def selftest() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "feed.md"
        t0 = now()
        # shape cases are policy/feed_test.rego; here: no entry refused, the old form refused
        ok &= overdue(f, "aaaa", t0) == -1
        ok &= append(f, "aaaa", "idp", "🔴 a\n🟡 b\n🟢 c\n⚪ d\n📍 e", t0) is not None
        # must permit: a fresh entry with TOUCHES/OVERLAP, then not overdue at +29 min, overdue at +31
        good = "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: none\n🔀 OVERLAP: none\n📍 e"
        ok &= append(f, "aaaa", "idp", good, t0) is None
        ok &= overdue(f, "aaaa", t0 + dt.timedelta(minutes=29)) is None
        ok &= overdue(f, "aaaa", t0 + dt.timedelta(minutes=31)) == 31 * 60
        # another session is judged on its own entries
        ok &= overdue(f, "bbbb", t0) == -1
        ok &= len(entries(f)) == 1 and entries(f)[0][3] == good.split("\n")
    print(f"{'ok  ' if ok else 'FAIL'}  feed-guard selftest: refuses no-entry and the old form (shape: policy/feed.rego), permits the new form, "
          f"overdue at 31 min and not at 29, per session")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("append"); a.add_argument("--session", required=True); a.add_argument("--lane", required=True)
    s = sub.add_parser("status"); s.add_argument("--n", type=int, default=5)
    sub.add_parser("selftest")
    for k in ("Stop", "SessionStart", "UserPromptSubmit"):
        sub.add_parser(k)
    args = ap.parse_args(argv)
    if args.cmd == "append":
        err = append(FEED, args.session[:8], args.lane, sys.stdin.read())
        print(f"FAIL  feed-guard: {err}" if err else f"ok    feed-guard: handoff appended to {FEED}"); return 1 if err else 0
    if args.cmd == "status":
        for e in entries(FEED)[-args.n:]:
            print(f"## {e[0].strftime('%Y-%m-%dT%H:%MZ')} · {e[1]} · {e[2]}\n" + "\n".join(e[3]) + "\n")
        return 0
    if args.cmd == "selftest":
        return selftest()
    return hook(args.cmd or "Stop")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
