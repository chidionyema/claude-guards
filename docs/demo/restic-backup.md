# Demo: restic estate backup

The estate's critical state is now backed up every night to storage we own
(Cloudflare R2), encrypted before it leaves this Mac, and the backup proved it can
give a file back — which is the only test of a backup that means anything.

## The run that proved it

First real backup, then a restore of the laws file, compared byte for byte
(2026-08-24, ~01:00 UTC):

```
$ ~/.claude/scripts/hc-wrap.sh estate-restic ~/.claude/scripts/estate/restic-backup.sh
latest snapshot 7686c2ed age 0:00:08.082480

$ restic restore latest --target <scratch> --include ~/AGENTS.md
Summary: Restored 3 / 1 files/dirs (98.173 KiB / 98.173 KiB) in 0:00

$ cmp ~/AGENTS.md <scratch>/Users/chidionyema/AGENTS.md && echo byte-identical
AGENTS.md: byte-identical

$ shasum -a 256 <both files>
5e3e585a12007e58 /Users/chidionyema/AGENTS.md
5e3e585a12007e58 <scratch>/Users/chidionyema/AGENTS.md
```

A secret-bearing file (`~/.estate/healthchecks/hc.env`) made the same round trip
byte-identical in the same drill. Two angles: `cmp` and independent sha256 hashes.

## It is watched

The backup job runs wrapped in the dead-man monitor. If the nightly run stops
happening, your phone gets a 🔴 within about 31 hours:

```
estate-restic | up | last_ping: 2026-08-24T01:00:00+00:00
```
