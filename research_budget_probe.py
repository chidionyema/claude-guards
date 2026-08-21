#!/usr/bin/env python3
"""What does WASTED research actually look like on this estate? Measure before building.

CLAUDE.md already states a delegation rule -- "before the SECOND exploratory grep/glob/Read
aimed at the same open question, spawn a haiku Explore subagent", with the tell being "3+
consecutive read-only calls with no edit between them". Nothing enforces it. Before enforcing
it literally, check what it would cost: the read-run distribution measured 2026-08-21 has
p50=2 and p75=4, so a limit of 3 would fire on a large share of ORDINARY runs, and a guard
that fires more than ~3 times a session is one an agent learns to ignore.

So measure three narrower signals that are waste by construction, not by opinion:

  1 REPEAT READ   the same file REGION read again, having already been read, with no write to
                  it in between. CLAUDE.md: "Never re-read an unchanged file."
  2 REPEAT SEARCH the same pattern searched again in the same session.
  3 NO DELEGATION read-only runs in sessions that never spawned a single subagent, which is
                  the cost signal: the main loop paying Opus rates for recon.

Reuses goal-guard's classify() so this cannot drift from the guard it calibrates.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude" / "scripts"))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "goalguard", Path.home() / ".claude" / "scripts" / "goal-guard.py")
GG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GG)

READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead", "WebFetch", "WebSearch"}


def tool_uses(line: str):
    try:
        obj = json.loads(line)
    except Exception:
        return
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("type") == "tool_use" and "name" in cur:
                yield cur.get("name"), cur.get("input") or {}
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def target_of(name: str, inp: dict) -> str | None:
    """A stable key for 'the thing this call looked at'. None when there isn't one."""
    if name in ("Read", "NotebookRead"):
        p = inp.get("file_path")
        if not p:
            return None
        # The REGION matters. Reading lines 1-50 and then 200-250 of one file is two
        # different looks, not a repeat; ignoring offset counted them as waste and
        # inflated the repeat-read number.
        return "read:%s#%s+%s" % (p, inp.get("offset") or 0, inp.get("limit") or 0)
    if name == "Grep":
        pat = inp.get("pattern")
        if not pat:
            return None
        return "grep:%s|%s" % (pat, inp.get("path") or "")
    if name == "Glob":
        p = inp.get("pattern")
        return "glob:" + str(p) if p else None
    if name in ("WebFetch",):
        u = inp.get("url")
        return "url:" + str(u) if u else None
    if name == "WebSearch":
        q = inp.get("query")
        return "web:" + str(q) if q else None
    if name == "Bash":
        c = (inp.get("command") or "").strip()
        # An identical shell command run twice is waste whatever it does, and it is the
        # 58.4% of this estate's calls that a tool-name-only instrument cannot see.
        return "bash:" + c if c else None
    return None


def scan(path: Path) -> dict:
    seen: dict[str, int] = {}          # target -> call index first seen
    written: set[str] = set()          # file paths written since
    repeat_read = 0
    repeat_search = 0
    agents = 0
    calls = 0
    runs: list[int] = []
    run = 0
    repeat_gap: list[int] = []
    try:
        with path.open(errors="replace") as fh:
            for line in fh:
                if '"tool_use"' not in line:
                    continue
                for name, inp in tool_uses(line):
                    calls += 1
                    if name == "Agent":
                        agents += 1
                    kind = GG.classify(name, {"tool_input": inp})
                    if kind == "READ":
                        run += 1
                    elif kind == "WRITE":
                        if run:
                            runs.append(run)
                        run = 0
                        fp = inp.get("file_path")
                        if fp:
                            written.add("read:" + str(fp))
                    key = target_of(name, inp)
                    if key is None:
                        continue
                    if key in seen:
                        if key.startswith("read:"):
                            stem = key.split("#", 1)[0]
                            if stem not in written:
                                repeat_read += 1
                                repeat_gap.append(calls - seen[key])
                        else:
                            repeat_search += 1
                            repeat_gap.append(calls - seen[key])
                    else:
                        seen[key] = calls
                    if key.startswith("read:") and key.split("#", 1)[0] in written:
                        written.discard(key.split("#", 1)[0])
                        seen[key] = calls
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    if run:
        runs.append(run)
    return {"calls": calls, "agents": agents, "repeat_read": repeat_read,
            "repeat_search": repeat_search, "runs": runs, "gaps": repeat_gap,
            "distinct": len(seen)}


def pct(vals, p):
    if not vals:
        return 0
    s = sorted(vals)
    i = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return s[i]


def main() -> int:
    root = Path.home() / ".claude" / "projects"
    files = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_size, reverse=True)
    files = [f for f in files if f.stat().st_size > 50_000][:80]
    print("scanning %d transcripts (>50KB)" % len(files))

    tot = Counter()
    per_session = []
    allruns, allgaps = [], []
    nodel_runs = []
    for f in files:
        r = scan(f)
        if r.get("error") or not r.get("calls"):
            continue
        per_session.append((f.stem[:8], r))
        for k in ("calls", "agents", "repeat_read", "repeat_search"):
            tot[k] += r[k]
        allruns += r["runs"]
        allgaps += r["gaps"]
        if r["agents"] == 0:
            nodel_runs += r["runs"]
    n = len(per_session)
    if not n:
        print("NO SESSIONS -- instrument failure")
        return 1

    print("\n" + "=" * 78)
    print("SIGNAL 1+2 -- work done twice")
    print("=" * 78)
    print("  sessions               : %d" % n)
    print("  tool calls             : %d" % tot["calls"])
    print("  REPEAT READS           : %-6d  %.2f%% of all calls, %.1f per session"
          % (tot["repeat_read"], 100 * tot["repeat_read"] / tot["calls"], tot["repeat_read"] / n))
    print("  REPEAT SEARCHES        : %-6d  %.2f%% of all calls, %.1f per session"
          % (tot["repeat_search"], 100 * tot["repeat_search"] / tot["calls"],
             tot["repeat_search"] / n))
    both = tot["repeat_read"] + tot["repeat_search"]
    print("  both, per session      : %.1f   <- a guard firing on EVERY one fires this often"
          % (both / n))
    if allgaps:
        print("  calls between the first look and the repeat: p50=%d p90=%d max=%d"
              % (pct(allgaps, 50), pct(allgaps, 90), max(allgaps)))

    print("\n  FIRING RATE if the guard only refuses a repeat seen within N calls:")
    print("  %-8s %-10s %s" % ("N", "fires", "per session"))
    for N in (5, 10, 20, 40, 80, 200, 10 ** 9):
        f = sum(1 for g in allgaps if g <= N)
        lbl = "any" if N > 10 ** 8 else str(N)
        rate = f / n
        band = ("NOISE" if rate >= 3 else "usable" if rate >= 0.6
                else "rare" if rate >= 0.15 else "INERT")
        print("  %-8s %-10d %.2f  %s" % (lbl, f, rate, band))

    print("\n" + "=" * 78)
    print("SIGNAL 3 -- does the main loop delegate at all?")
    print("=" * 78)
    nodel = [s for s, r in per_session if r["agents"] == 0]
    print("  sessions that spawned ZERO subagents : %d of %d (%.0f%%)"
          % (len(nodel), n, 100 * len(nodel) / n))
    print("  total Agent spawns across the corpus : %d  (%.1f per session)"
          % (tot["agents"], tot["agents"] / n))
    if nodel_runs:
        print("  read-only runs inside those sessions : %d, p50=%d p90=%d max=%d"
              % (len(nodel_runs), pct(nodel_runs, 50), pct(nodel_runs, 90), max(nodel_runs)))

    print("\n" + "=" * 78)
    print("WHAT A LITERAL READING OF CLAUDE.MD WOULD COST")
    print("=" * 78)
    for limit in (2, 3, 4, 6, 8, 12, 16):
        f = sum(1 for x in allruns if x >= limit)
        rate = f / n
        band = ("NOISE" if rate >= 3 else "usable" if rate >= 0.6
                else "rare" if rate >= 0.15 else "INERT")
        print("  refuse the %2dth consecutive read-only call: %5d fires, %6.2f/session  %s"
              % (limit, f, rate, band))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
