# canonical-root-guard — onboarding

## What it is for

You said on 2026-08-23 that everyone should be working from one location and that worktrees and
projects were littered everywhere. They were: 67 git checkouts across 6 roots, only 12 of them
under `~/dev/code`. Six agents cannot see each other, so each one works in whatever directory it
happens to start in, and two of them end up editing two copies of the same repo.

This guard is the machine remembering the rule so no session has to. When a session starts
outside `~/dev/code`, it says so, once, and says what to do instead.

## What it costs

Nothing you will notice. It is a few milliseconds of Python at session start, no network, no
API calls, no money. It runs only when a session begins, not on every command.

## What it watches, and what it will never touch

It reads one thing: the directory a session started in. It moves nothing, deletes nothing and
changes no file, ever. It prints a notice and exits 0. If its own lookup breaks, it stays quiet
and lets the session run — a guard that blocks work when it malfunctions is a guard that gets
deleted.

Some paths are exempt on purpose, because moving them would break the estate:

- `~/.claude` and `~/.claude/scripts` — Claude Code reads its settings, skills and the laws from
  there, and 29 scheduled jobs name `~/.claude/scripts` as the program they run. Those jobs
  resolve their own program path, so a symlink left behind would not save them.
- `~/AGENTS.md` — `laws-link-guard.py` owns that file's layout and treats a move as damage.
- `~/.hermes/scripts` — wraps the scheduled jobs.
- `~/Documents/code/prospector` — `com.chidionyema.reflect` runs every four hours and has that
  path hardcoded twice. Moving it would silently stop the estate's only self-measurement.
- Session scratchpad worktrees under `/private/tmp` — temporary, and the session that made one
  removes it itself.

## Where it lives

`~/.claude/scripts/canonical-root-guard.py`, in the `claude-guards` repository, wired as a
`SessionStart` hook in `~/.claude/settings.json`.

## How to turn it off

One command:

```
python3 -c "import json,pathlib; p=pathlib.Path.home()/'.claude/settings.json'; s=json.loads(p.read_text()); [m['hooks'].remove(h) for a in [s['hooks']['SessionStart']] for m in a for h in list(m['hooks']) if 'canonical-root-guard' in h['command']]; p.write_text(json.dumps(s,indent=2)+'\n')"
```

New sessions stop seeing it immediately. Sessions already running are unaffected either way,
because the hook only fires at start.

## How to turn it back on

Restore the entry, or `cp ~/.claude/settings.json.bak-canonical-root ~/.claude/settings.json`.

## What goes wrong

The one failure worth knowing about: the guard tells a session it is in the wrong place, and the
session decides to fix that by moving the directory. That is the thing that breaks the estate,
which is why the notice says three times not to move anything. Consolidation is one agent's job,
done with the scheduled-job paths updated in the same change.

The second: it can only see where a session STARTED. A session that starts in the root and then
works elsewhere will not be caught. That is a known limit, accepted because catching it would
mean a check on every command, and a guard that speaks constantly is a guard that gets ignored.
