# Friction relay, onboarding

## What it is for

Six Claude sessions run on this machine at once and none of them can read the
others. When the founder tells one session it is doing something wrong, the
other five never hear it, so they keep doing it. He then has to say the same
thing again to the next session, and again to the one after that.

The relay closes that gap. Every session, when it starts, is shown what he
complained about to any session in the last six hours. It is the only way one
correction reaches all six.

## What it costs

Nothing in money. It makes no model calls at all. It reads a small file that a
background job has already prepared, so the session start it runs on is not
measurably slower.

## What it watches and what it changes

It reads the transcripts under `~/.claude/projects`, which Claude Code writes
whether the relay runs or not. It changes nothing. Its only output is text
printed into a session as that session begins.

It shows at most six complaints and says how many it held back, so a bad hour
does not bury the session start under a wall of text.

## Where it lives

```
~/.claude/scripts/friction-relay.py         the script
~/.claude/state/friction-relay.json         the cache it reads
~/.claude/state/logs/friction-relay.out     what the refresh job printed
~/Library/LaunchAgents/ai.estate.friction-relay.plist
```

Two things run it. A hook on `SessionStart` in `~/.claude/settings.json` prints
the complaints into a starting session. A launchd job, `ai.estate.friction-relay`,
rebuilds the cache every 600 seconds so the hook never has to walk the disk.

## How to turn it off

```
launchctl bootout gui/501/ai.estate.friction-relay
```

That stops the cache being rebuilt, and within ten minutes the relay has nothing
recent to say and goes quiet on its own. To silence it the same second, delete
the cache as well:

```
rm -f ~/.claude/state/friction-relay.json
```

Nothing else depends on either file. Sessions start normally without it.

## How to turn it back on

```
launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.estate.friction-relay.plist
```

The cache rebuilds on the next tick and the next session start shows the
complaints again.

## What can go wrong

It fails open, deliberately and in every case. An empty cache, a stale cache,
unreadable JSON or a payload shaped wrong all end the same way: it prints
nothing and exits 0. A hook that can break a session start is a hook somebody
deletes by lunchtime, so this one cannot.

The failure that is possible is a quiet one. If the launchd job stops, the cache
stops moving and the relay keeps showing whatever it last held until those
entries age past six hours, after which it says nothing. Silence therefore means
either a calm six hours or a dead refresh job, and the two look the same from
inside a session. The log at `~/.claude/state/logs/friction-relay.out` is what
tells them apart.

It judges a complaint with a word list, so it is not exact. It can carry a line
that was not really a complaint, and it can miss one phrased mildly. Carrying an
extra line costs a session nothing; missing one costs the founder a repeat.
