#!/usr/bin/env python3
"""Two instruments disagree by 24x on the same corpus. Find which one is lying before using either.

  session_noise.py   longest read-only run, worst session : 1017
  calibrate_threshold.py  longest run in the WHOLE corpus :   43

HYPOTHESIS: they are not measuring the same thing. session_noise counted calls since the last
Edit/Write TOOL. calibrate uses goal-guard's classify(), which also counts a Bash command
containing a mutating verb as a state change. Most work on this estate is done through Bash
heredocs and python -, so under the first definition a session that wrote forty files reads as
forty untouched read-only calls.

If that is the cause, re-running with the narrow definition must reproduce a number near 1017.
That is the test. A hypothesis that cannot be reproduced is not the cause.
"""
from __future__ import annotations
import json, sys, importlib.util
from collections import Counter, defaultdict
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "goalguard", Path.home() / ".claude" / "scripts" / "goal-guard.py")
GG = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(GG)


def tool_uses(line):
    try: obj = json.loads(line)
    except Exception: return
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("type") == "tool_use" and "name" in cur:
                yield cur.get("name"), cur.get("input") or {}
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


root = Path.home() / ".claude" / "projects"
files = [f for f in root.rglob("*.jsonl") if f.stat().st_size > 50_000]
files.sort(key=lambda p: p.stat().st_size, reverse=True)
files = files[:80]

write_src = Counter()          # where did WRITE verdicts come from?
runs_guard = []                # goal-guard definition
runs_narrow = []               # Edit/Write TOOL only
per_session_runs = defaultdict(list)
NARROW = {"Edit", "Write", "NotebookEdit"}

for f in files:
    g = n = 0
    for line in f.open(errors="replace"):
        if '"tool_use"' not in line:
            continue
        for name, inp in tool_uses(line):
            kind = GG.classify(name, {"tool_input": inp})
            if kind == "WRITE":
                write_src["bash-verb" if name == "Bash" else "write-tool"] += 1
                if g: runs_guard.append(g); per_session_runs[f.stem].append(g)
                g = 0
            elif kind == "READ":
                g += 1
            if name in NARROW:
                if n: runs_narrow.append(n)
                n = 0
            else:
                n += 1
    if g: runs_guard.append(g); per_session_runs[f.stem].append(g)
    if n: runs_narrow.append(n)

print("=" * 78)
print("IS THE HYPOTHESIS RIGHT? re-measure with the NARROW definition")
print("=" * 78)
print("  goal-guard definition   max run : %d   (n=%d)" % (max(runs_guard), len(runs_guard)))
print("  narrow  Edit/Write-only max run : %d   (n=%d)" % (max(runs_narrow), len(runs_narrow)))
print("  session_noise.py reported       : 1017")
print()
print("  WRITE verdicts by source:")
tot = sum(write_src.values())
for k, v in write_src.most_common():
    print("    %-12s %6d  %5.1f%%" % (k, v, 100 * v / tot))
print()
if max(runs_narrow) > 500:
    print("  CONFIRMED. The narrow definition reproduces the large number. The two instruments")
    print("  measured different things; neither was broken. goal-guard's definition is the one")
    print("  that matters, because it is the one the guard actually counts with.")
else:
    print("  NOT REPRODUCED. The hypothesis is wrong and something else explains the gap.")

print()
print("=" * 78)
print("ANGLE 2, REPLACED -- firing rate per session is the real calibration knob")
print("=" * 78)
print("  The terminal-run class was 23 items and the 3.76x separation rested on ONE of them.")
print("  A ratio from one sample is not a measurement, so that angle is discarded.")
print("  This is what the research actually asked for: calibrate against the hook's own")
print("  false-positive budget. A guard nobody can ignore fires about once a session.")
print()
ns = len(per_session_runs)
print("  %-7s %-9s %-13s %-11s %s" % ("limit", "fires", "per session", "% of runs", "verdict"))
for limit in (8, 10, 12, 14, 16, 18, 20, 25, 30, 43):
    fires = sum(1 for x in runs_guard if x >= limit)
    per = fires / ns
    if per >= 3:      v = "NOISE -- learned and ignored"
    elif per >= 0.6:  v = "usable"
    elif per >= 0.15: v = "rare"
    else:             v = "INERT -- may as well not exist"
    print("  %-7d %-9d %-13.2f %-11.2f %s" % (limit, fires, per, 100*fires/len(runs_guard), v))
print()
print("  sessions in corpus: %d" % ns)
srt = sorted(runs_guard)
print("  p50=%d p90=%d p95=%d p99=%d max=%d"
      % (srt[len(srt)//2], srt[int(.90*len(srt))], srt[int(.95*len(srt))],
         srt[int(.99*len(srt))], srt[-1]))
