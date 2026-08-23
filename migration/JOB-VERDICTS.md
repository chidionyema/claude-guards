# Are the 15 jobs worth reloading?

Measured 2026-08-23 from `launchctl list` plus the tail of each job's own log.
Nothing here is from memory. Source data: `job-audit.json`.

## A. Already dead. Do NOT reload. (5)

The move cannot break these because they are not running now.

| job | evidence |
|---|---|
| `ai.hermes.idle-engine` | not loaded, log empty, untouched 17 days |
| `ai.hermes.keepawake` | not loaded, log empty, untouched 23 days |
| `ai.hermes.lease-guard` | not loaded, last log is the same clock error repeated |
| `com.prospector.scheduler` | not loaded, has NO log file at all, never ran here |
| `com.signalengine.daemon` | not loaded, stopped 2026-08-21, DuckDB table missing |

`com.prospector.scheduler` is correctly dead: production moved to Fly.
Deleting these 5 plists is the smaller road than repairing paths inside them.

## B. Doing real work. Reload. (4)

| job | what it actually produced |
|---|---|
| `com.prospector.backup` | `STORE_BACKUP PASS mirror=repo/2026-08-23T113015Z.bundle bytes=71176969`, and it prunes to the newest 14 |
| `com.prospector.offsite-backup` | freshness check, all four targets OK, oldest 11.5h |
| `com.chidionyema.reflect` | writes `store/ops/method_metrics.json` every run |
| `ai.hermes.runaway-reaper` | `matched=0` every run, a guard that has never fired |

`reflect` and `runaway-reaper` are worth a question, not a reload:
reflect has written the same three numbers for days and nothing reads the file;
runaway-reaper guards a tree that is being retired.

## C. Loaded, running, and failing every single run. (6)

These are the interesting ones. All exit non-zero, all have done so for
a long time, and nothing has changed as a result.

| job | its own verdict line |
|---|---|
| `com.prospector.process-audit` | `FAIL: 22 failing/undocumented, 26 warnings` |
| `com.prospector.launchd-held` | `LAUNCHD HELD FAIL 5 finding(s)` |
| `com.chidionyema.graphify-sweep` | `VERDICT: ❌ see docs/GRAPHIFY_ENFORCEMENT_SPEC.md` |
| `com.prospector.estate-inventory` | `38 resources, 28 undescribed` |
| `com.prospector.log-rotation` | `1 finding(s). Apply with --fix.` |
| `com.prospector-control.receipt-bridge` | `cannot read ~/.prospector/deploy/engine/supervisord.conf` |

LAW 28: an instrument nobody reads is not an instrument. Six jobs have been
reporting failure on a schedule and no state changed. Either somebody starts
reading them or they are noise with a cron entry.

`com.prospector.launchd-held` is the sharpest example. It has been correctly
reporting `NOT HELD ai.hermes.lease-guard` for days, which is a true statement
about group A above, and nobody acted on it.

`com.prospector.estate-inventory` has a log timestamp of 1970, so its own
freshness cannot be trusted.

## What this changes about the move

Reload list drops from 15 to 10: the 4 in B and the 6 in C.
Group A needs no reload and probably needs deleting.

## Do any of these jobs change code, and is it visible?

Measured 2026-08-23 across all 32 plists, reading the real program behind the
`launchd_receipt.py` wrapper rather than the wrapper itself.

**No scheduled job raises a pull request.** One file matches `gh pr create`,
`founder_board.py:536`, and the match is inside a docstring describing a past
incident. It is not a call.

**Three jobs run in fix mode**, and none of them edits source code:

| job | what `--fix` changes |
|---|---|
| `com.chidionyema.graphify-sweep` | regenerates the code graph |
| `com.prospector.log-rotation` | rotates and prunes log files |
| `com.prospector.offsite-backup` | writes backup copies |

So the machine is not editing its own source on a timer.

**The visibility gap is the agents, not the jobs.** The malformed comment in
`ai.estate.kimi-bridge.plist` was found and fixed by a Claude session editing
`~/Library/LaunchAgents` directly. No pull request, no review, no record
outside two agent transcripts. That is the same for every change either of us
has made to files outside a git repository today.

Files under `~/.claude/scripts` ARE in git and were pushed, so those changes
are reviewable after the fact. Files in `~/Library/LaunchAgents` are not in
any repository at all.
