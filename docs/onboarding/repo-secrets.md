# Repository secrets — what it is and how to stop it

## What is this for

To stop a credential reaching a git remote, and to find the ones already there.

Those are two different jobs. The first is cheap and can block. The second is slow and has to run on
a schedule, because a key in a commit from March is readable today no matter what the current tip
looks like.

## What it costs

`--diff` reads one diff. Under a second on a normal push, and it is the only part in anyone's way.

`--history` walks every commit in a repository. Minutes on the large ones. It runs on a schedule
over the public repositories, never in front of a push.

No network and no money in either mode. Everything is local pattern matching.

## What it watches or changes

It watches and changes nothing. It never rewrites history, never edits a file, and never rotates
anything. It reads and it refuses.

When it blocks a push, the credential is still in your commit. Removing it is your work, and
rotating it is the part people skip: if it was ever committed, treat it as disclosed even if the
push was refused, because it is in your local reflog and in any worktree sharing that object store.

## Where it lives

```
repo_secrets.py     the scanner, both modes
secret-scrub.py     the separate Stop hook for local log files
```

`secret-scrub.py` is not this and does not overlap with it. It cleans the local files that collect
keys by accident. It has never looked at a repository.

## How to turn it off

Remove the pre-push invocation from the repository's hooks. For the scheduled history pass, unload
its launchd job.

Turning off `--diff` while leaving `--history` running means you find the key the morning after it
was published. That is still better than nothing, and it is not the same as a gate.

## How to turn it back on

Restore the pre-push hook and bootstrap the job.

## What goes wrong

**A false positive blocks a real push.** This is the failure that gets a gate deleted, so the STRONG
patterns are all anchored on a provider's own prefix and length. The loose `secret = <long string>`
pattern is WEAK by classification and reports without blocking, because on its first run it produced
three hits and all three were environment variable names.

**A key with no recognisable shape gets through.** A 40-character hex string is a git SHA, an MD5, a
key, or nothing. Anchoring on provider prefixes is what makes the STRONG set safe to block on, and
the cost of that choice is that a home-grown token format is not detected. That is a known limit and
not a bug to file.

**A key is already in history.** `--diff` cannot see it, by design, because it reads what the push
adds. `--history` is the mode for that question and it must be run before a repository is made
public. Making a repository public is the one operation where the slow mode is not optional.
