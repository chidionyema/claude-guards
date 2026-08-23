# The drill register

## What it is

A list of the ways this estate can be recovered, and the date each one last
proved it works. A backup nobody has restored is not a backup, and a rollback
nobody has run is not a rollback. The register is what stops either from being
believed on the strength of a green tick.

`drills/register.json` holds ten entries. Three have a command and pass. Seven
have no command yet, and each one carries the sentence describing what needs
writing. The live answer is always `drills/run.py --list`; this table goes stale
and the register does not.

| drill | written | what breaks without it |
|---|---|---|
| no-anthropic | yes | Anthropic is unreachable and no agent can think |
| rebuild | yes | this Mac dies and the estate has to come back on a new machine |
| estate-bundle-restore | yes | a commit exists only on this Mac and the Mac dies |
| offsite-backup-restore | no | the prospector data is gone and the offsite copy is all that is left |
| secret-rotation | no | a credential leaks and has to be replaced |
| telegram-delivery | no | something breaks at 03:00 and the message never arrives |
| windows-rebuild | no | the rebuild has to happen on a machine that is not a Mac |
| github-gone | no | GitHub is unreachable and both estate repositories are there |
| cloudflare-gone | no | R2 holds the offsite copy and Cloudflare is the way in |
| stripe-gone | no | payments stop and there is no second processor |

Read 2026-08-23. An earlier version of this page said six entries and named a
`fly-rollback` drill that is not in the register.

## How it runs

The launch agent `ai.estate.drills` fires Mondays at 04:30 and runs the whole
register. Results go to `~/.claude/state/drills.jsonl`, one line per run, and a
summary goes to `ESTATE_BOARD.jsonl`.

**It has not fired yet.** `launchctl print gui/501/ai.estate.drills` reported
`runs = 0` on 2026-08-23: the job is loaded and its definition is correct, and
its first Monday has not come round. Every pass on the register so far was
produced by an agent typing `--all` by hand. That is worth knowing, because a
schedule nobody has watched fire is a schedule nobody has tested.

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
