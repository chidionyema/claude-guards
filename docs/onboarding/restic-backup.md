# Onboarding: restic estate backup

## What is this for

The old hand-built backup scripts once produced 43 success receipts while copying
nothing. This replaces the backup engine with restic, a widely used open-source tool
whose one job is backups, and whose proof is a restore. The old backup jobs are all
still running untouched, as you ordered — this runs alongside them as the primary,
they are the fallback.

## What does it cost

Storage on Cloudflare R2 the estate already pays for (the backup set is about 50 MB;
R2's free tier is 10 GB, so today the marginal cost is zero). The software is free
(BSD licence). Nightly upload is incremental — only changed data moves.

## What does it watch or change

It reads and copies, never modifies: the estate's un-versioned critical state —
the laws (`~/AGENTS.md`), agent state and ledgers (`~/.claude/state`), memory and
checkpoints, scheduled-job definitions (`~/Library/LaunchAgents`), monitor data
(`~/.estate`), and the estate config directories. Everything is encrypted on this
Mac before upload; the storage provider sees only ciphertext.

## Where it lives

- Engine: `restic` (installed via Homebrew).
- Script: `~/.claude/scripts/estate/restic-backup.sh`, in git.
- Schedule: launchd job `com.estate.restic-backup`, nightly 03:30, wrapped in the
  dead-man monitor (check `estate-restic`) so silent death reaches your phone.
- The data: R2 bucket the estate owns, under the `restic/` prefix.
- The repo password: `~/.estate/restic/password` (owner-only). A copy sits in
  `~/.claude/state/`, which the old offsite job ships off-box — so losing this Mac
  does not lose the backups.

## How do I turn it off

    launchctl bootout gui/501/com.estate.restic-backup

The old backup jobs keep running; nothing else changes.

## How do I turn it back on

    launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.estate.restic-backup.plist

## What goes wrong

- If two backup runs overlap, the second refuses with a lock error and exits; the
  monitor turns the check red and your phone hears about it. `restic unlock` clears
  a stale lock once the holder is confirmed dead.
- If the repo password file is lost AND this Mac dies, the backups are unreadable —
  that is why the copy in `~/.claude/state/` travels with the old offsite job.
- Restores are drilled, not assumed: the restore command and byte-identical proof
  are in the demo page.
