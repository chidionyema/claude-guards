# recovery-posture — the demo

Every block below is output that was captured from a real run and pasted. Where
a run produced something wrong, the wrong output is here too, because the point
of this page is what the instrument actually says.

## The command

```
python3 ~/.claude/scripts/drills/run.py --run recovery-posture
```

## What it says now, 2026-08-23 23:17 UTC

```
41 job definitions on disk, 40 loaded, 1 deliberately retired, 40 of 40 can recover themselves
RETIRED ai.hermes.gateway: REQ-116: the old estate held the Telegram poll and made The Architect deaf for 31.5 hours. One token, one poller.

DRILL PASSED: every job on this Mac restarts, reschedules or is explicitly retired, and every one of them has run.
```

Through the harness, which is how it runs on a schedule:

```
recovery-posture  PASS  rc=0  0.7s  DRILL PASSED: every job on this Mac restarts, reschedules or is explicitly retired, and every one of them has run.
```

## The bug it was written for

The drill did not find this one — it was written because of it, an hour after
`founder_board.py` was taught to grade a job by whether it had run rather than
by its exit code. `launchctl list` reported exit 0 for both jobs the whole time.

`com.founder.agentcert` and `com.prospector.launchd-held` fire on the same
second every hour. Both sit behind `estate-gate`, which lets two jobs run at
once, so one of them lost the race every time — and losing the race meant losing
the whole hour. Between them they had never completed a single run. From
`~/.estate/state/gate.log`:

```
2026-08-23T21:35:12Z com.founder.agentcert DEFERRED all 2 slots busy load=4.72
2026-08-23T22:35:13Z com.founder.agentcert DEFERRED 1/2 all 2 slots busy load=4.88
```

`load=4.72` on a 12-core machine. It was nearly idle, and the job was still sent
away for an hour.

`~/.estate` commit `7dbd0b0` made a job queue for a slot rather than give up its
turn. Both then ran within seconds of being asked:

```
2026-08-23T23:12:30Z com.prospector.launchd-held RUN load=9.94 slot=.../gate.slot.2 waited=0s
2026-08-23T23:12:34Z com.prospector.launchd-held DONE rc=1
2026-08-23T23:12:35Z com.founder.agentcert RUN load=9.94 slot=.../gate.slot.2 waited=5s
2026-08-23T23:13:42Z com.founder.agentcert DONE rc=0
```

`waited=5s` is the whole fix. Under the old code that line was a lost hour.

## The false positive on its own first run

The first version of this drill was wrong, and this is what it printed:

```
41 job definitions on disk, 40 loaded, 40 can recover themselves, 1 cannot

CANNOT RECOVER  com.estate.bundlepush
                the gate has seen it and it has never once completed a run: it loses its turn every time

DRILL FAILED: 1 jobs cannot recover themselves.
```

`com.estate.bundlepush` was not starved. It was in the middle of a run, pushing
a repository bundle offsite every seven seconds, and had simply not finished.
The drill was grading a proxy: no record of a finished run also means running
right now.

Three different problems leave that same trace and need three different repairs,
so the drill now separates them by cause. Proved on synthetic state:

```
  PASS  job.starved      -> it has never once completed a run: it loses its turn every time
  PASS  job.dying        -> the gate started it 30 minutes ago, no process is left, and it never r
  PASS  job.fine         -> no finding
  PASS  job.stale        -> its last completed run was 25.0h ago and it is meant to run every 1.0h
  PASS  job.never-seen   -> no finding
  PASS  running-now      -> no finding while a gate process is alive
```
