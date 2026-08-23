# Load-bearing files, under version control

LAW 24: if it is load-bearing, it is in git.

This directory holds a copy of every scheduled job on this Mac. Its siblings
`laws/` and `settings/` hold the other files the estate depends on that no
repository held. What is tracked is listed in `../tracked.json`, with the reason
each one is there.

These are copies, not symlinks. `launchd` reads the originals in
`~/Library/LaunchAgents`. This is the reviewable record of them.

## Keeping the two in step

    python3 tracked.py --check    # exits 1 if any tracked file has drifted
    python3 tracked.py --pull     # bring the live files in, then commit

`--check` is the guard. Without it the copy rots the first time somebody edits a
live file, and a stale record is worse than none because it still reads as one.

## Before adding anything here

Scan it for secrets and verify the matches rather than trusting the pattern.
Checked 2026-08-23 across all 32 plists: every one of the 23 credential-shaped
matches was a filesystem path.

## Remember what launchctl actually does

`launchctl` runs the definition it loaded at bootstrap, NOT the file on disk.
Editing a plist in either place changes nothing until the job is booted out and
back in. A stale job reports exit 0 while running the old definition.
