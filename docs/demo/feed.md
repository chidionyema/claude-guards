# The feed, demo

Every session writes a six-line handoff to `~/.estate/feed.md` every 15 minutes:
what is blocked, what is active, what is done, what is pending, which files it is
touching, and whose work it overlaps. The guard refuses a handoff that is missing a
line, that touches a file another session touched inside the last two hours without
naming that session, or that arrives on the old shape.

Since crew#786 the handoff also publishes. The last 48 hours of the feed, cleared by
the secret scanner, land on the idp `state/live-diagram` branch as `docs/FEED.md`,
and once an hour the same step regenerates `docs/NEXT.md`, the page the founder
reads when he asks "what is next".

## What the founder sees

```
https://github.com/chidionyema/idp/blob/state/live-diagram/docs/FEED.md   the live feed, 48 h
https://github.com/chidionyema/idp/blob/state/live-diagram/docs/NEXT.md   what is next, hourly
```

## Run the demo

```
python3 ~/.claude/scripts/feed-guard.py selftest                    # the guard's own proof
python3 ~/.claude/scripts/feed-guard.py append --session <id> --lane <dir> < handoff.txt
                                                                    # ends with: ok  feed-publish: handoff 2026-..Z
python3 ~/.claude/scripts/feed-guard.py check --session <id>        # overdue at 16 minutes, not at 14
```

A handoff that names a file a peer touched, without naming the peer on the
🔀 OVERLAP line, is refused with the peer's id and the file so you can name them.
If the secret scanner is not installed the handoff is still written locally and the
receipt says `BLIND feed-publish: gitleaks not installed`; nothing unscanned is ever
published.
