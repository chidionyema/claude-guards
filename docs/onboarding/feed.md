# The feed, onboarding

## What it is for

Several sessions work on this estate at once and none of them can see the others.
The feed is the one place they meet: a plain text file, one handoff per session per
15 minutes, read back to every session when it starts and summarised for the founder
when he asks for status. Crew#786 made it visible to him too: the handoff publishes
the feed to the idp state branch, so the founder reads it from a page, not a laptop.

## The shape

Six lines, in this order: `🔴 Blocked`, `🟡 Active`, `🟢 Done`, `⚪ Pending`,
`🔧 TOUCHES` (the files this session is editing), `🔀 OVERLAP` (the sessions whose
work it crosses), then `📎 FACTS` (a URL) and `📍 State` (the checkpoint file). The
shape is a policy (`policy/feed.rego`), not prose; `opa test` proves it.

## What the guard refuses

- A handoff missing a line, or on the old shape.
- A lane another session holds, unless OVERLAP names the holder (crew#331).
- A path in TOUCHES that another session touched inside two hours, unless OVERLAP
  names that session (crew#786). The refusal names the session and the path.
- Being late: a session with no handoff for 16 minutes is flagged; 14 is fine.

## What publishing does, and what it never does

After a handoff is on disk the guard renders the last 48 hours, runs the secret
scanner (gitleaks) over the text, and commits `docs/FEED.md` to a shallow clone of
the idp `state/live-diagram` branch under `~/.estate/live-diagram`. Once an hour it
also runs `bin/estate-next` to regenerate `docs/NEXT.md`. If the scanner is missing
or does not answer, nothing is published and the receipt says so; a failure to
publish never fails the handoff already written. `FEED_GUARD_NO_PUBLISH=1` turns
publishing off for tests. The idp repository is named once, from the environment
(`ESTATE_IDP_REPO`, or `ESTATE_IDP_REMOTE` for a full URL).

## Where things live

- Guard: `~/.claude/scripts/feed-guard.py`; policy: `policy/feed.rego`.
- Feed: `~/.estate/feed.md`; publish clone: `~/.estate/live-diagram`.
- Tests: `tests/test_incident_crew786_*.py`.
