# Self-healing across the estate, and every edge case it does not cover

Founder, 2026-08-23: "we need to ensure the estate is resillet and review self
healing across the board napping all edge cases". This is that review.

Every number below was measured on 2026-08-23/24, and the command that produced
it is named beside it. Where a mechanism has never fired in production, this page
says so rather than counting it as coverage: a repair path that has only ever run
in a test is a hope with a test suite, and LAW 19 already refuses that reasoning
about vendors. The same rule applies to our own code.

## The seven layers, and what each one heals

| layer | what heals it | proved by | fired in production |
|---|---|---|---|
| scheduled jobs | launchd KeepAlive, RunAtLoad, StartInterval | `drills/check_recovery_posture.py` | yes, 40 of 40 |
| job contention | `estate-gate` slot queue and bounded deferral | 6 synthetic cases + 1 live | partly, see below |
| live services | launchd KeepAlive on both | `launchctl list`, plist | yes |
| inference drift | scheduler fails closed, no paid call | `cron_model_drift_axes` | yes, twice, and it hid |
| data integrity | `check_db_integrity.py` repairs index damage | drill, 8 databases | yes, once |
| recovery paths | the drill register | `drills/run.py --list` | 8 of 13 written |
| delivery | `check_telegram_delivery.py` | drill | yes |

## 1. Scheduled jobs — closed

    $ /usr/bin/python3 drills/check_recovery_posture.py
    41 job definitions on disk, 40 loaded, 1 deliberately retired, 40 of 40 can
    recover themselves
    DRILL PASSED

Six ways a job stops recovering itself are graded: its program is missing from
disk, it has no KeepAlive or RunAtLoad or interval at all, it is a live service
whose first crash is permanent, it is gated and never gets a turn, it is loaded
with no plist so it dies at the next reboot, or its plist is on disk and it is
not loaded. The drill runs daily.

The one retired job is `ai.hermes.gateway`, and it is named with its reason
rather than left absent, because a job missing from launchd with no entry beside
it is an accident nobody noticed.

## 2. Job contention — fixed, and three of its repair paths have never run live

This was the real hole. `com.founder.agentcert` and `com.prospector.launchd-held`
fire on the same second every hour, lost the slot race every time, and had never
completed a single run, while launchd reported exit 0 for both. Sixteen of 43
lost turns were "all slots busy" and ten of those happened at a load average
under 5.5 on twelve cores. The machine was idle and the job still lost an hour.

The gate now queues for a slot instead of giving up the turn, reclaims a slot
from a dead process, steals one from a holder that has passed the one-hour
ceiling without killing it, and bounds consecutive deferrals so nothing can go
stale forever.

    2026-08-23T23:12:35Z com.founder.agentcert RUN load=9.94 slot=.../gate.slot.2 waited=5s
    2026-08-23T23:13:42Z com.founder.agentcert DONE rc=0

That `waited=5s` was a lost hour under the old code. Both starved jobs wrote
`gate.lastrun` for the first time.

**The honest gap.** Counted in `~/.estate/state/gate.log` on 2026-08-24: FORCED 0,
slots reclaimed 0, STARVED 0, runs that queued rather than lost their turn 1. So
one of the four repair paths has run in production and three have not. They pass
six constructed cases on a fake HOME. That is a reading, not a proof, and this
page will not call it one until the log shows each of them firing on a real job.

## 3. Live services — both restart themselves

    ai.architect.gateway      KeepAlive=True RunAtLoad=True
    com.chidionyema.maestro   KeepAlive=True RunAtLoad=True

The Architect answers on Telegram: an inbound message at 23:50:39 produced a
response of 513 characters in 15.1 seconds. maestro cycles its estate audit and
reports its own state.

**The honest gap.** KeepAlive restarts a process that exits. It does nothing for a
process that stays up and stops doing its job, which is the failure mode both of
these actually have. maestro currently reports `State: CRISIS` with 39 findings
and 5 standing P0 alarms while its process is perfectly healthy. A liveness check
is not a usefulness check.

## 4. Inference drift — the guard worked and still cost a day

The scheduler refuses to run a cron job whose global inference config changed
after the job was created and that is not pinned to a model. It makes no paid
call. That is the correct behaviour and it is what a fail-closed guard should do:
it was built after a real $7.73 incident.

What it did next is the problem. It alerted once, then stayed skipped
indefinitely, and one of the two jobs used the `[drift_skip:silent]` variant,
which does not alert at all after the first time. Two of The Architect's six
active cron jobs had been dead since 22:17Z — `watch-estate-map` and
`session-coordination-monitor`, both of which are the founder's own monitoring
and both of which deliver to his phone. The monitors were the thing that broke,
so nothing was left to report that anything had broken.

Both are now pinned to `anthropic` / `claude-sonnet-5`, which is what the global
config already resolves to, and the guard confirms it with a paired control:

    8cfca8bec02d watch-estate-map              pinned  drifting_axes=[]
                 control, unpinned                     drifting_axes=['model']
    570b73d05313 session-coordination-monitor  pinned  drifting_axes=[]
                 control, unpinned                     drifting_axes=['model']

**The class, not the instance.** A guard that fails closed and then stops speaking
has converted a spend risk into a silence, and silence is the failure the founder
named first: "silent failue is the worst kid of failues". Skipped is a third
state beside pass and fail, and nothing on this estate currently counts it. The
repair is a check that reads `cron list` and reports any job whose last run was a
skip, which is the same shape as `check_recovery_posture.py` pointed at cron
instead of launchd. It is not written yet, and until it is, this exact failure
recurs the next time the global model changes.

## 5. Data integrity — heals itself, within a stated limit

`check_db_integrity.py` runs `PRAGMA integrity_check` over every database, and
repairs missing index entries itself because those are recoverable from the table
data. It refuses to touch anything worse and reports instead, because rebuilding
an index over a damaged page hides the damage rather than fixing it.

It exists because `Documents/code/prospector/store/prospector.db` was missing
eight index entries across four indexes and had been for at least two days.
`PRAGMA quick_check` returns `ok` on that exact file, because it skips index
content by design. The cheap check passed while the real one failed.

## 6. Recovery paths — 8 of 13 proved

    $ drills/run.py --list
    no-anthropic PASS · rebuild PASS · estate-bundle-restore PASS
    offsite-backup-restore PASS · key-escrow-restore PASS · telegram-delivery PASS
    db-integrity PASS · recovery-posture PASS
    secret-rotation NOT WRITTEN · windows-rebuild NOT WRITTEN
    github-gone NOT WRITTEN · cloudflare-gone NOT WRITTEN · stripe-gone NOT WRITTEN

The five unwritten ones are the five largest single points of failure left, and
each is a vendor. `github-gone` is the sharpest: every recovery path this estate
has starts with `git clone` from github.com, and the offsite bundles do not close
that hole, because for a repository that has a remote the push script uploads
only what the remote does not already hold.

A drill with no command is counted and named in every report but does not fail
the check, deliberately. A gate that is red forever gets ignored, and an ignored
gate is worse than none.

## Edge cases this estate does not currently heal

Each of these is a real gap, not a hypothetical.

1. **A job that runs and does nothing.** Every instrument here grades whether a
   job got a turn. None grades whether the turn accomplished anything.
   `com.prospector.launchd-held` exits rc=1 every run and nothing decides whether
   that is a finding-exit or a failure.
2. **A skipped cron job.** Section 4. Skipped is neither pass nor fail and nothing
   counts it.
3. **A healthy process doing useless work.** maestro is up and in CRISIS at the
   same time, and no mechanism connects those two facts.
4. **A vendor disappearing.** Five drills unwritten, and GitHub is the one that
   takes every other recovery path with it.
5. **A repair path that has never run.** Three of the gate's four, section 2.
6. **A log whose timestamps are unusable.** `com.prospector.estate-inventory`
   reports a log 496,534 hours old, so any freshness check on it is meaningless.
7. **The founder being the notifier.** Several of these were found because he
   said something was wrong, not because anything reported it. LAW 36 is explicit
   that his complaint is an outage report about the platform.

## What closes the largest gap next

A cron-skip check, built as `check_recovery_posture.py` was, pointed at
`hermes cron list` instead of `launchctl list`, and registered as a daily drill.
It closes edge case 2 outright, and it is the same instrument shape that already
closed edge case 4 for launchd. Everything else on the list above is larger than
one turn and belongs on the board as an issue.
