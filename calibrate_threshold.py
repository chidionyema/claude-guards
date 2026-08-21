#!/usr/bin/env python3
"""Calibrate readonly_run_limit from OUR OWN transcripts, because no published number exists.

The literature is explicit that this cannot be borrowed. The one telemetry-only drift detector
with a real evaluation (arXiv 2608.02464, 2,823 episodes) calibrates its threshold per deployment
against a healthy-run distribution, and its accuracy falls to AUROC 0.527 -- chance -- when moved
to a different model family without recalibrating. Engineering convention offers 3-6 consecutive
IDENTICAL calls and a generic ceiling of 20, neither measured and neither the same signal.

So: measure the signal here, on this estate, with the SAME classifier the guard uses. The guard is
imported rather than reimplemented, so the calibration cannot drift from the thing it calibrates.

TWO ANGLES, because one distribution is a reading and not a proof (LAW 15).

  ANGLE 1  the distribution of every read-only run in the corpus. A threshold at percentile P
           fires on (100-P)% of runs. That is the false-positive budget, stated as a number.

  ANGLE 2  a labelled positive class that needs no judgement: a TERMINAL run -- one that ends the
           session with no write ever following it. The session read, and read, and then stopped
           without acting. That is drift by construction, not by opinion. A good threshold sits
           above most ordinary runs and below most terminal ones.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude" / "scripts"))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "goalguard", Path.home() / ".claude" / "scripts" / "goal-guard.py")
GG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GG)


def tool_uses(line: str):
    """Every tool_use block on one transcript line, whatever the nesting."""
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


def runs_in(path: Path):
    """Yield (length, terminal) for every maximal run of consecutive READ calls."""
    run = 0
    out = []
    try:
        with path.open(errors="replace") as fh:
            for line in fh:
                if '"tool_use"' not in line:
                    continue
                for name, inp in tool_uses(line):
                    kind = GG.classify(name, {"tool_input": inp})
                    if kind == "READ":
                        run += 1
                    elif kind == "WRITE":
                        if run:
                            out.append((run, False))
                        run = 0
                    # UNKNOWN moves nothing, exactly as the guard behaves
    except Exception:
        return []
    if run:
        out.append((run, True))          # terminal: session ended still reading
    return out


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0
    i = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def main() -> int:
    root = Path.home() / ".claude" / "projects"
    files = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_size, reverse=True)
    files = [f for f in files if f.stat().st_size > 50_000][:80]
    print("scanning %d transcripts (>50KB), largest first" % len(files))

    ordinary, terminal = [], []
    for f in files:
        for length, is_term in runs_in(f):
            (terminal if is_term else ordinary).append(length)

    allruns = sorted(ordinary + terminal)
    ordinary.sort()
    terminal.sort()
    if not allruns:
        print("NO RUNS FOUND -- the parser found no tool_use blocks. Instrument failure.")
        return 1

    print("\n" + "=" * 78)
    print("ANGLE 1 -- every read-only run in the corpus")
    print("=" * 78)
    print("  runs measured        : %d" % len(allruns))
    print("  ordinary (ended in a write) : %d" % len(ordinary))
    print("  terminal (session stopped still reading) : %d" % len(terminal))
    print()
    print("  %-6s %-8s %s" % ("pctile", "length", "fires on this share of all runs"))
    for p in (50, 75, 90, 95, 97, 99, 99.5, 100):
        v = pct(allruns, p)
        above = sum(1 for x in allruns if x >= v)
        print("  %-6s %-8d %.2f%%  (%d runs)" % (p, v, 100 * above / len(allruns), above))

    print("\n" + "=" * 78)
    print("ANGLE 2 -- does the threshold separate ordinary runs from terminal ones?")
    print("=" * 78)
    print("  A terminal run is drift by construction: the session read and never acted again.")
    print()
    print("  %-8s %-22s %-22s %s" % ("limit", "ordinary runs caught", "terminal runs caught", "ratio"))
    best = None
    for limit in (10, 12, 15, 20, 25, 30, 40, 50, 60, 80, 100):
        o = sum(1 for x in ordinary if x >= limit)
        t = sum(1 for x in terminal if x >= limit)
        orate = 100 * o / len(ordinary) if ordinary else 0
        trate = 100 * t / len(terminal) if terminal else 0
        ratio = (trate / orate) if orate else float("inf")
        mark = ""
        if orate > 0 and trate > 0:
            if best is None or ratio > best[1]:
                best, mark = (limit, ratio), ""
        print("  %-8d %5.2f%% (%4d)        %5.2f%% (%4d)        %.2fx"
              % (limit, orate, o, trate, t, ratio))

    print("\n" + "=" * 78)
    print("READ THIS BEFORE USING THE NUMBER")
    print("=" * 78)
    print("  A high ratio means the limit is more likely to catch a run that really did end in")
    print("  nothing than one that ended in work. It is NOT an accuracy score: terminal runs are")
    print("  a small and biased class (a session can also end mid-read because the founder")
    print("  interrupted it, or because it was compacted). Treat it as one angle of two.")
    if best:
        print("\n  best separation in this corpus: limit=%d at %.2fx" % best)
    print("\n  current default in lanes.json: 25")
    v25o = sum(1 for x in ordinary if x >= 25)
    v25t = sum(1 for x in terminal if x >= 25)
    print("  at 25 it fires on %d ordinary and %d terminal runs (%.2f%% of all runs)"
          % (v25o, v25t, 100 * (v25o + v25t) / len(allruns)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
