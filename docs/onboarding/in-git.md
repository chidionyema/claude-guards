# in-git

## What it is for

LAW 24 says anything load-bearing is in git. This is the machine that checks it, so nobody
has to ask an agent and get a different answer each time. That happened three times in one
afternoon: two of the three answers were wrong, because each agent looked at a different
part of the estate and guessed about the rest.

## What it watches

Six classes, declared in `estate/load-bearing.json` so adding one is data, not code.

- **runners** every program a launchd job actually executes
- **declared** the laws, settings, agent definitions, skills, job definitions
- **repos** every estate repo clean, on the branch it should be on, and pushed
- **mirrors** the live file and its committed copy still identical
- **secrets** a credential file has a committed example naming its keys, and no values
- **offsite** every repo has a recent verified bundle away from this machine

A class that cannot run reports that it could not run and fails the sweep. It never passes
because it did not look.

## What it costs

Nothing beyond the machine it runs on. One hourly run, a few seconds of git commands, no
paid service. Telegram delivery reuses the bot the estate already has.

## What it changes

Nothing. It only reads and reports. It never commits, never pushes, never deletes.

## Where it lives

- the sweep: `~/.claude/scripts/estate/in-git.py`
- what counts as load-bearing: `~/.claude/scripts/estate/load-bearing.json`
- the shared answer to "is this kept?": `~/.claude/scripts/estate/ingit.py`
- the schedule: `~/Library/LaunchAgents/com.founder.ingit.plist`
- the last result: `~/.claude/state/in-git-status.json`

## How to turn it off

```
launchctl bootout gui/$(id -u)/com.founder.ingit
```

The messages stop immediately. Nothing else in the estate depends on it.

## How to turn it back on

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.founder.ingit.plist
```

## What goes wrong

The commonest report is a repository with uncommitted changes, and that is usually another
session mid-edit rather than a fault. It clears itself on the next run once that session
commits. A hole that survives several hours is a real one.

The second commonest is a checkout sitting on a branch that is not main. Nothing is lost
when that happens, but work committed there does not reach main, so it looks lost. The fix
is to push that branch rather than to switch it, because another session is usually standing
on it.
