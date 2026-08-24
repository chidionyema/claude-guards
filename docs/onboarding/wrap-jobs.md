# Wrapping jobs for dead-man monitoring — what it is and how to stop it

## What is this for

To put a launchd job under a dead-man check, so that silence is an alarm.

`launchctl list` shows the last exit code. A job whose script was moved by a `git mv` shows 0 with
no stderr and looks healthy for as long as you care to watch it. Forty-three of those hid a dead
dashboard. A dead-man check inverts it: the receiver expects a ping on a schedule, so a job that
stops running is louder than one that fails.

## What it costs

Two HTTPS requests per job run, both fire-and-forget. Healthchecks.io on the free tier.

The tool itself is a migration and costs nothing after it has finished. It edits plists and exits.

## What it watches or changes

**Report mode changes nothing** and is the default. It prints every job, whether it is already
wrapped, and every refusal with its reason.

`--fix LABEL [LABEL ...]` writes. It takes explicit labels rather than sweeping everything, because
editing 34 plists in one go is 34 chances to typo a path into a job that then reports exit 0 while
doing nothing, which is the exact incident this exists to prevent.

## Where it lives

```
estate/wrap-jobs.py                the migration, report mode by default
estate/hc-wrap.sh                  the wrapper the plists point at
estate/measure-wrap-coverage.sh    the permanent instrument
```

This tool is not the instrument. When every wrappable job is wrapped it has no work left. What keeps
the estate honest afterwards is `measure-wrap-coverage.sh`, which counts from `launchctl list`
rather than from this script's record of what it believes it did.

## How to turn it off

There is nothing running to turn off. It is a migration you invoke.

To unwrap one job, remove the first two entries from its `ProgramArguments` and reload it:

```
launchctl bootout gui/$(id -u)/<label>
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist
```

Reloading matters. launchctl runs the definition it loaded at bootstrap, not the plist on disk, so
editing the file alone changes nothing.

## How to turn it back on

```
python3 estate/wrap-jobs.py --fix <label>
```

## What goes wrong

**The receiver is down.** The job runs normally and the ping is lost. `hc-wrap.sh` never fails a job
because monitoring is unavailable. What you lose is that run's evidence, not the run.

**A KeepAlive job gets wrapped by hand.** It pings start once at boot and never pings an exit, so the
check goes green and stays green while telling you nothing. This tool refuses those eight jobs for
that reason, and doing it manually is how the refusal gets defeated.

**The plist is edited without a reload.** The job keeps running its old loaded definition. Every
change here ends in a bootout and a bootstrap for that reason.

**The coverage number disagrees with what you wrapped.** Believe the coverage number.
`measure-wrap-coverage.sh` reads `launchctl list`, which is what is actually loaded. This tool's
output is a record of intent.
