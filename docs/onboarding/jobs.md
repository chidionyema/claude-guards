# Scheduled jobs

## What this is for

Twenty-nine things run on a schedule on this machine: the guards that check the
estate, the agents that answer, the backups. Each one used to BE a macOS plist
file with this account's home directory typed into it. That made two things
impossible at once. A new machine could not be rebuilt, because the files named
a home directory that did not exist there. And a different operating system was
not a port, it was a rewrite.

Now a job is declared once, in `jobs/jobs.json`, with no operating system in it,
and a renderer generates the platform's own file from that declaration.

## What it costs

Nothing to run. The renderers are two Python files and they only run when a job
is added or a machine is rebuilt. The manifest is 29 entries in one tracked
file, so a new job is a reviewable diff rather than a plist typed by hand into a
directory nobody was watching.

## What it changes

`jobs/render.py --write` writes `~/Library/LaunchAgents`. That is the only thing
here that touches the live machine, and it will not overwrite a plist whose
content already matches, because fourteen of them carry hand-written comments
saying why the job is shaped the way it is and a rewrite would drop them.

Two placeholders carry the parts that are not portable. `{HOME}` is the account's
home directory. A name in braces such as `{PYTHON3_SYSTEM}` or `{BASH}` is a
program, and `jobs/platforms.json` is the only file that says what it means on
each platform. A search path is declared as a list of directories, so each
platform joins it with its own separator instead of inheriting a colon.

## Where it lives

```
jobs/jobs.json           the 29 jobs, with no platform in them
jobs/platforms.json      the only file holding a platform's own names
jobs/render.py           macOS. --check compares the manifest to the live directory
jobs/render_windows.py   Windows. --check reports what Task Scheduler does not keep
```

## How to see the state

```
jobs/render.py --check            is the live machine in step with the manifest?
jobs/render_windows.py --check    what would a Windows machine lose?
```

Neither writes anything. The first is also run by the estate's hourly sweep, so
drift reaches the board without anyone typing a command.

## How to turn it off

The renderers are not services and nothing schedules them, so there is nothing
running to stop. To stop the sweep that checks them:

```
launchctl bootout gui/$(id -u)/ai.estate.tracked-guard
```

To turn it back on:

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.estate.tracked-guard.plist
```

## What goes wrong

**launchd runs the definition it loaded, not the file on disk.** Writing a plist
changes nothing until the job is booted out and back in. A job can report exit 0
for weeks while running code that has moved.

**A Windows rendering is not a working Windows machine.** `render_windows.py`
produces XML that Task Scheduler will accept, and every job still loses
something on the way: nine lose a process priority, six use `KeepAlive` as a
supervisor that restarts on any exit where Task Scheduler only restarts on
failure, and one uses a file-watch trigger Windows has no equivalent for. Until
one of those tasks has actually been imported and run on Windows, this is a file
format exercise, which is what the `windows-rebuild` entry in `drills/run.py
--list` says.

**Five installed jobs are not in the manifest and that is expected.** They are
vendor jobs, or jobs another agent installed. `render.py --check` lists them
under "installed but not declared" rather than deleting them.
