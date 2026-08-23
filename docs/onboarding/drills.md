# The drill register

## What it is

A list of the ways this estate can be recovered, and the date each one last
proved it works. A backup nobody has restored is not a backup, and a rollback
nobody has run is not a rollback. The register is what stops either from being
believed on the strength of a green tick.

`drills/register.json` holds six entries today. Two have a command and pass.
Four have no command yet, and each one carries the sentence describing what
needs writing:

| drill | what breaks without it |
|---|---|
| rebuild | this Mac dies and the estate has to come back on a new machine |
| estate-bundle-restore | a commit exists only on this Mac and the Mac dies |
| offsite-backup-restore | the prospector data is gone and the offsite copy is all that is left |
| secret-rotation | a credential leaks and has to be replaced |
| telegram-delivery | something breaks at 03:00 and the message never arrives |
| fly-rollback | a deploy takes production down |

## How it runs

The launch agent `ai.estate.drills` fires Mondays at 04:30 and runs the whole
register. Results go to `~/.claude/state/drills.jsonl`, one line per run, and a
summary goes to `ESTATE_BOARD.jsonl`.

Nothing needs to be typed for any of that. The commands below are here so an
agent can use them and so you can see what the machine is doing, not because
the register needs a person.

    drills/run.py --list     what is registered and when each last passed
    drills/run.py --all      run everything now
    drills/run.py --check    exit 1 if a drill is failing or has gone stale

## How to turn it off

    launchctl bootout gui/501/ai.estate.drills

That stops the weekly run and nothing else. The register and its history stay on
disk, and `drills/run.py --list` still reports the last known state of each path.
To bring it back, `launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.estate.drills.plist`.

## Why NOT WRITTEN does not make it red

A drill with no command yet is counted and named in every report, but it does
not fail the check. A gate that is red forever gets ignored, and an ignored gate
is worse than none, because the next person reads a red board and assumes it has
always been red. The pressure to write the missing four comes from the count
leading every board line, not from a permanent failure.
