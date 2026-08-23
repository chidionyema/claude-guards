# ~/Library/LaunchAgents, under version control

Every scheduled job on this Mac used to live in exactly one place: an unversioned
directory. An agent could edit one and the only record was a chat transcript.
That is what this directory fixes.

These files are copies, not symlinks. `launchd` reads the originals in
`~/Library/LaunchAgents`. This directory is the reviewable record of them.

Checked before the first commit, 2026-08-23: no plist carries a secret value.
Every credential-shaped match was a filesystem path.

## Keeping the two in step

    python3 launchagents/sync.py --check    # exits 1 if they differ
    python3 launchagents/sync.py --pull     # copy the live files in here

`--check` runs in CI. A job edited on the machine and not committed fails it.

## Remember what launchctl actually does

`launchctl` runs the definition it loaded at bootstrap, NOT the file on disk.
Editing a plist here or there changes nothing until the job is booted out and
back in. A stale job reports exit 0 while running the old definition.
