# A job that is not running now says so

## What this is for

Your ops dashboard was dead tonight and every instrument pointed at it was green.
You said it plainly: "otto was tellingne it ws and verifed confidently". Otto was
not lying to you. Otto was reading a board that could not tell the difference
between a job that passed and a job that never ran.

Thirty-one scheduled jobs on this Mac go through a load shedder called
`estate-gate`. When the machine is busy it makes a job give up its turn, and it
tells launchd exit 0, because giving up a turn is not a failure. That part was
right. What was missing was a limit. A job could give up its turn forever, and
every one of those turns was recorded as a success.

Between 18:35 and 22:35 today that happened 43 times across 12 jobs. One of them
was the estate audit, which is the data behind your dashboard. It gave up four
turns in a row, its output went 183 minutes old against a 120 minute deadline,
and the page refused to serve. Nothing anywhere went red.

## What it does now

Two changes, and between them a job that is not running becomes visible.

A job may lose two turns in a row. On the third it runs, whatever the machine is
doing. That bounds how stale anything on this Mac can get to two intervals, by
construction, rather than by somebody noticing. The one exception is a machine so
loaded that running would make things worse, above four times the core count. Then
the job gives up again and reports a failure code instead of a success code, so it
shows up as not run rather than as fine.

Every real run now writes down when it happened, per job. Your board reads those
timestamps and carries a row called "Jobs losing every turn". It counts jobs that
have lost two or more turns and says how long since each one last did any work.

## What else this caught

Your board watched 18 of the 39 jobs on this Mac. The list of which jobs to watch
named four prefixes, and everything outside them was skipped in silence. Three
failing jobs were invisible to it for that reason, including the board's own job
and The Architect's gateway. It now watches all 39.

Two of those were not really failures, and the board now says so. Its own job ends
with exit 1 whenever the estate has a red row, which is a finding and not a crash.
And a job with a live process id is running at this instant, so the exit code
beside it belongs to the previous run and is history.

## What it costs

Nothing in money. In time, a job that has waited two turns runs during a busy
period instead of a quiet one, which is the trade being made on purpose: a stale
dashboard costs you more than one extra job on a loaded machine. The emergency
ceiling is what stops that becoming a pile-on.

## What it changes on disk

Three small text files per job under `~/.estate/state`, none larger than a line:
`gate.defers.<label>` holds the run of turns lost so far, `gate.lastrun.<label>`
holds when it last really ran, and `gate.log` is the running record of every
deferral, forced run and completion.

## Where it lives

`~/.estate/guards/bin/estate-gate` is the shedder, committed in `~/.estate`.
The row is `_jobs_not_running()` in `~/.claude/scripts/founder_board.py`, and it
appears on the page at `~/.claude/state/founder-board.html`, which is what
`/ops` and the board serve.

## How to turn it off

Turning off the bound, keeping the shedding:

```
launchctl setenv ESTATE_GATE_MAX_DEFERS 999
```

Turning off the shedder entirely, so every job runs the moment its timer fires:

```
launchctl setenv ESTATE_GATE_OFF 1
```

## How to turn it back on

```
launchctl unsetenv ESTATE_GATE_MAX_DEFERS; launchctl unsetenv ESTATE_GATE_OFF
```

Both take effect on each job's next tick. Nothing has to be reloaded.

## What goes wrong

**The row reads zero on a quiet machine.** That is correct and it is the point.
Zero means every job took its turn. It is not the same as the row being absent,
which would mean nothing measured.

**A job appears with "never observed running".** It has lost turns and has not
completed a run since the timestamp file existed, so there is nothing to compare
against. It resolves itself the first time that job finishes.

**The counter resets after a real run.** Only consecutive lost turns count. A job
that ran an hour ago and gives up one turn now is behaving correctly and will not
appear.

**A job crashes rather than being deferred.** This row will not catch that. That is
the "Background jobs failing" row above it, and the two are separate on purpose,
because a job that fails and a job that never starts are different problems.
