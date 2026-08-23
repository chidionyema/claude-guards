# The silent failure, counted and then closed

Every block below is pasted from a real run on 2026-08-23, with the command that
produced it above it. Nothing here is typed by hand.

## The class, counted

`estate-gate` writes one line per decision. Counting the deferrals gives the size
of the problem.

```
python3 - <<'PY'
import os,collections
p=os.path.expanduser("~/.estate/state/gate.log")
lines=[l.rstrip() for l in open(p)]
d=[l for l in lines if " DEFERRED" in l]
labels=collections.Counter(l.split()[1] for l in d)
print(f"log lines      : {len(lines)}")
print(f"DEFERRED events: {len(d)} across {len(labels)} jobs")
print(f"window         : {d[0].split()[0]} .. {d[-1].split()[0]}")
for lab,n in labels.most_common(5): print(f"  {n:3}  {lab}")
PY
```

```
log lines      : 86
DEFERRED events: 43 across 12 jobs
window         : 2026-08-23T18:35:08Z .. 2026-08-23T22:35:21Z
    5  com.prospector.launchd-held
    5  com.founder.agentcert
    5  ai.estate.tracked-guard
    5  com.founder.estatewatch
    4  com.founder.estateaudit
```

Forty-three turns lost in four hours. Every one of them reported exit 0 to
launchd, which is what a successful run reports.

## What that did to the dashboard

`com.founder.estateaudit` is fourth on that list with four turns lost in a row.
Its output feeds the page. The admin view said what happened, in its own words:

```
STALE 183 minutes old, deadline is 120. /audit is REFUSING to serve it.
Live links · 0.
```

The job was reporting success the whole time.

## The allow-list that hid three more

The board only watched jobs whose label began with one of four prefixes. Running
the old list and the new list over the same `launchctl list` output:

```
old filter: 7 failing of 18 watched
new filter: 10 failing of 39 watched

failures the board could never see (3):
   com.founder.board (exit 1)
   ai.architect.gateway (exit 1)
   com.founder.ingit (exit 1)
```

Twenty-one of the thirty-nine jobs on this Mac were outside the board's view,
including the board's own job.

## Two of those three were not failures, and the board now says so

`launchctl list`, the two rows:

```
-	1	com.founder.board
91037	1	ai.architect.gateway
```

`founder_board.py` ends `return 1 if board["bad"] else 0`, so its exit 1 is a
count of findings, not a crash. And `ai.architect.gateway` has a live process id
beside its exit code, so it is running at this instant and the 1 belongs to the
previous run. Counting either as a current failure is the same defect pointed the
other way. After the fix, the same input:

```
bad      | Background jobs failing | 9 of 39 | com.chidionyema.guard-selftest (exit 1); com.chidionyema.graphify-sweep (exit 1); com.estate.bundlepush (exit 1); com.founder.lawenforcement (exit 1); com.prospector.process-audit (exit 1)
good     | Jobs losing every turn | 0 |
```

Ten became nine, and the two removed were the two that were not broken.

## The bound, proved on the gate itself

Six cases were run against `estate-gate` in an isolated HOME. The two that matter:

- deferred twice, then forced to run on the third turn under normal load
- above the emergency ceiling on the third turn, exits 75 instead of 0

Exit 75 is `EX_TEMPFAIL`. launchd stores the number, and a number a reader can
grade is the whole difference between not running and looking like passing.

## The row on the founder's page

```
grep -o "Jobs losing every turn" ~/.claude/state/founder-board.html
```

```
Jobs losing every turn
```

It is on the page he opens, not only in the JSON.

## What the row says right now

```
good     | Jobs losing every turn | 0 |
```

Zero is the correct answer at this moment: since the bound landed, no job has lost
two turns in a row. Before tonight this row did not exist, and the honest reading
of its absence is that nobody could have told.
