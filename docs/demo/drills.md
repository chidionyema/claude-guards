# What you see when the drills run

Nothing, unless something is wrong. That is the point.

Every Monday at 04:30 the machine takes each of the estate's escape routes and
checks it still goes anywhere. Then it writes one line on the board every
session reads at startup, so a session that opens on Tuesday morning already
knows.

The weekly job has fired once, on 2026-08-23, and it was kicked by hand rather
than by the clock: `launchctl print gui/501/ai.estate.drills` had reported
`runs = 0` since the job was created, so it was started deliberately to find out
whether the scheduled path worked. It did. The first run on the clock is Monday
2026-08-24 at 04:30. The runs below were started by an agent, which is the thing
the schedule exists to replace.

That launchd run is also the one that caught something an agent run could not.
Four of the five written drills passed; `rebuild` failed with `every declared job
rendered for this home: expected 31, got 30`, because a new launch agent had been
declared in `jobs/jobs.json` on this laptop and not yet pushed. The rebuild drill
builds the estate from a fresh clone, so a job that is not in the remote does not
come back on a new machine. It was right to be red.

## The real run, 2026-08-23

    $ /usr/bin/python3 drills/run.py --all

      no-anthropic           PASS   rc=0    100.4s  VERDICT: the estate can still work without Anthropic.
      rebuild                PASS   rc=0    6.4s  DRILL PASSED
      estate-bundle-restore  PASS   rc=0    0.2s  4 of the last 17 pushes cloned back standalone, newest push 3.5h ago

That run put this line on `ESTATE_BOARD.jsonl`, which is the only part of it a
person ever sees:

    {"ts": "2026-08-23T20:45:46Z", "from": "drills", "kind": "drills-passed",
     "text": "All 3 written recovery drills passed. 7 recovery paths still have
     no drill and are therefore unproven: offsite-backup-restore,
     secret-rotation, telegram-delivery, windows-rebuild, github-gone,
     cloudflare-gone, stripe-gone."}

A bad week names the thing that broke, not the place to go and look. This one is
real too, from the run 20 minutes earlier, before the checker was fixed:

    {"ts": "2026-08-23T20:25:26Z", "from": "drills", "kind": "drills-failed",
     "text": "1 of 3 recovery drills failed: estate-bundle-restore (  None
     None  restore=None) -> /Users/chidionyema/.claude/state/drills/
     estate-bundle-restore-2026-08-23T202526Z.log. 7 more recovery paths have
     no drill at all: ..."}

The count of unproven paths leads both lines on purpose. It is the number that
should be going down, and it is the one thing an agent cannot quietly leave
alone while reporting green.

## What that failure turned out to be

The drill was right to be red and wrong about why, which is the more expensive
kind of red. The bundle pusher writes `{"event":"skipped"}` when another copy of
itself already holds the lock, and those rows carry no slug and no verdict
because no push was attempted. The checker counted them as pushes that proved
nothing, so the estate's own concurrency control turned the drill red while
every real push in the window had passed.

Underneath it was a real fault the drill could not see: one copy of the pusher
held the lock for 4586 seconds and three runs skipped behind it. The checker now
reads the skips for that, and only that:

      3 of the last 20 runs skipped on a held lock; longest wait 76 min
      that wedge cleared: 2026-08-23T17:15:57Z pushed 3.5h ago, after it
      4 of the last 17 pushes cloned back standalone, newest push 3.5h ago

A wedge over an hour with nothing pushed since fails the drill. A wedge a later
push cleared reports as history, because a check that stays red after the thing
recovered is one people learn to ignore.
