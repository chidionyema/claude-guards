# GitHub is gone — what it looks like when it runs

The drill coverage report named this the most valuable unwritten drill on the estate: 22 asset
slots rested on it and it did not exist. This is it, written.

## The question

Every load-bearing repository except `~/.claude` points at github.com. If that account is suspended,
or the org is deleted, or the machine's disk fails on the same day, what comes back?

## The answer, today

```
$ python3 drills/check_github_gone.py
  ok       ~/.claude                  standalone bundle 0.1d old, 0.6 MB
  ok       ~/.claude/scripts          standalone bundle 0.1d old, 2.8 MB
  ok       ~/dev/code/hermes-v2       standalone bundle 0.1d old, 1.1 MB
  ok       ~/dev/code/maestro         standalone bundle 0.1d old, 0.8 MB
  ok       ~/dev/code/crew            standalone bundle 0.1d old, 6.3 MB
  ok       ~/dev/code/idp             standalone bundle 0.1d old, 1.5 MB
  ok       ~/dev/code/estate-secrets  standalone bundle 0.1d old, 0.0 MB
  ok       ~/dev/code/survival-stack  standalone bundle 0.1d old, 0.4 MB
  ok       ~/dev/code/agent-guard     standalone bundle 0.1d old, 0.0 MB
  ok       ~/Documents/code/prospector standalone bundle 0.1d old, 119.4 MB
  ok       ~/Documents/code/prospector-live standalone bundle 0.1d old, 117.6 MB
  ok       ~/Documents/code/signalengine standalone bundle 0.1d old, 1.0 MB
  ok       ~/.estate                  standalone bundle 0.1d old, 0.3 MB

GITHUB-GONE GREEN: all 13 load-bearing repos restore from R2 alone.
```

13 repositories, 250 MB, recoverable with rclone and git and nothing from GitHub.

## Why the existing drill did not answer this

`check_bundle_restore.py` asks whether the newest bundle receipt says a restore worked. It passes on
a `verify-ok` receipt, and `verify-ok` is an incremental bundle checked against the local repo.
`estate_bundle_push.sh` says so in its own header: restoring one of those needs the remote as well
as the bundle, so it is not a full escrow of GitHub.

There was a second hole underneath it. A repo whose remote already holds every commit was skipped by
the pusher outright, on the line `[ "${n:-0}" -gt 0 ] || continue`. Measured on 2026-08-24: R2 held
no standalone copy of any load-bearing repository at all, while the bundle drill was green.

So the estate had a passing backup drill and no way back from GitHub, at the same time.

## What a pass means

For every repo in `estate/load-bearing.json`, R2 holds a bundle written with `git bundle create
--all`, which was cloned back standalone at upload time. The receipt's mode starts with `full` and
its restore reads `clone-ok`, and it is fresher than the age bar.

Nothing in that sentence is an inference. Each part is a field in a receipt written when the upload
happened.

## BLIND, not green

If the receipts file or the declaration cannot be read, it prints BLIND and exits 2. A drill that
loses its evidence never returns a verdict, because a green that means "I could not look" is worse
than a red.
