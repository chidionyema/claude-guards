# Where this estate lives

## What it is for

Two repositories hold everything an agent on this machine can change. Before them,
the only record of a change to the laws, a scheduled job or a guard was a chat
transcript, and nobody could review it after the fact. LAW 24 is the rule; these
two repositories are where it is kept.

## The two repositories

| repository | holds | tracked files |
|---|---|---|
| `chidionyema/claude-estate` | `~/.claude`: the laws, settings, agent definitions, skills, project memory, conversation transcripts | 1651 |
| `chidionyema/claude-guards` | `~/.claude/scripts`: the guards, the hooks, the job manifest, the drills, the board writer | 180 |

Both are **private**, and that is not decoration. The first holds conversation
transcripts. The second was found public on 2026-08-23 with 48 files carrying
this machine's home path and six production hostnames in them.

`claude-guards` is registered inside `claude-estate` as a git submodule at
`scripts/`. One clone with `--recurse-submodules` gets both.

## The one trap, because it has bitten three times

The parent repository records a **pointer** to one commit of the submodule. A
commit made inside `scripts/` and not recorded in the parent is invisible to a
clone. Nothing on this machine can see that, because this machine already has
the commit. Only a clone finds out.

So: a commit in `scripts/` and the pointer move are one action, in the same turn,
every time. Two checks catch it if that is forgotten. `tracked.py --check` runs
every 30 minutes and fails on a stale pointer. The rebuild drill clones both
repositories into a throwaway home and asserts the result is complete; it failed
twice on 2026-08-23 for exactly this, and both failures were real.

## What it costs

Nothing. Two private repositories on a free GitHub account, and the commit and
push already run themselves.

## What changes them without being asked

`ai.estate.tracked-guard` runs `tracked.py --sync` every 30 minutes: it copies the
live files into the repository, commits, pushes, and writes one line to
`ESTATE_BOARD.jsonl`. `scripts/hooks/pre-commit` refuses any commit whose staged
content looks like a credential, reading the staged blob rather than the working
tree, and reporting `file:line` only so a refusal never prints the thing it stopped.

## How a new machine gets them

```
git clone --recurse-submodules https://github.com/chidionyema/claude-estate.git ~/.claude
python3 ~/.claude/scripts/tracked.py --restore
python3 ~/.claude/scripts/jobs/render.py --write
```

That is not the whole rebuild. 29 jobs render from one manifest, but 14 steps
still need a person, and 5 of those are browser sign-ins that no agent may ever do
as him. `rebuild/drill.sh` runs the whole thing weekly into a throwaway home and
reports the number, so the 14 is measured rather than remembered.

## How to turn it off

```
launchctl bootout gui/$(id -u)/ai.estate.tracked-guard
```

Committing and pushing stop immediately. Nothing else breaks: the repositories
stay where they are and the files on disk are untouched.

## How to turn it back on

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.estate.tracked-guard.plist
```

## What goes wrong

The commonest is `index.lock: File exists` in `~/.claude`. Six sessions and a
scheduled job share one checkout, so two git processes collide. Wait and retry;
remove the lock only after checking that no git process holds it and the file has
stopped changing.

The second is a checkout parked on a branch that is not `main`. Work committed
there does not reach main and looks lost. `estate/in-git.py` reports it hourly.
Push that branch rather than switching it, because another session is usually
standing on it.
