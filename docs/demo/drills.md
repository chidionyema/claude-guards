# What you see when the drills run

Nothing, unless something is wrong. That is the point.

Every Monday at 04:30 the machine takes each of the estate's escape routes and
checks it still goes anywhere. Then it writes one line on the board every
session reads at startup, so a session that opens on Tuesday morning already
knows.

A good week reads like this:

    All 2 written recovery drills passed. 4 recovery paths still have no
    drill and are therefore unproven: offsite-backup-restore,
    secret-rotation, telegram-delivery, fly-rollback.

A bad week names the thing that broke, not the place to go and look:

    1 of 2 recovery drills failed: rebuild (every declared job rendered for
    this home: expected 29, got 28). 4 more recovery paths have no drill at
    all.

The count of unproven paths leads both lines on purpose. It is the number that
should be going down, and it is the one thing an agent cannot quietly leave
alone while reporting green.

## What passed on 2026-08-23

    rebuild                PASS   11.3s   the estate rebuilt from its own
                                          repositories into a throwaway home,
                                          14 manual steps remaining
    estate-bundle-restore  PASS    0.4s   4 of the last 20 pushes cloned back
                                          standalone, newest push 1.8h ago
