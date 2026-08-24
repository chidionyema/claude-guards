# GitHub is gone — what it is and how to stop it

## What is this for

Twelve of the thirteen load-bearing repositories on this estate have their only off-machine copy on
github.com. That is one company holding the whole history. This drill proves there is a second copy
that does not need them.

It exists because the backup drill that was already green did not prove this. It graded incremental
bundles, which need the remote to restore, so a green reading meant "GitHub plus this bundle works"
and never "this bundle alone works".

## What it costs

The drill itself is a read of one receipts file. Under a second, no network.

What it grades costs more. `estate_bundle_push.sh` writes a full `--all` bundle of every declared
repo to Cloudflare R2 on a weekly cycle. That is about 250 MB per full round, dominated by the two
prospector repositories at 119 MB and 118 MB. R2 egress is free and storage at this size is cents a
month.

## What it watches or changes

It watches and changes nothing. It reads `estate/load-bearing.json` for the list of repositories and
the escrow receipts for what R2 actually holds. It writes no files and uploads nothing.

The uploading is `estate_bundle_push.sh` under `com.estate.bundlepush`. This drill is only the
grader, which is deliberate: a tool that both performs a backup and certifies it will certify it.

## Where it lives

```
drills/check_github_gone.py       the drill
drills/register.json              registers it, so coverage rules may point at it
estate/estate_bundle_push.sh      the thing it grades
estate/load-bearing.json          the list of repositories that must be covered
```

## How to turn it off

Remove `github-gone` from `drills/register.json`. The nightly `drills/run.py --all` stops running
it, and every coverage rule pointing at it becomes unclassified rather than silently covered, which
is the correct reading.

Do not turn off `com.estate.bundlepush` and leave this registered. That gives you a red drill every
night with nobody able to fix it.

## How to turn it back on

Put the row back in `drills/register.json`.

## What goes wrong

**The bundles go stale.** The bar is an age in days. A bundle older than that is reported by name
with its age, because a two-month-old copy of a repository that changes hourly is not a backup of
anything you have.

**A new repository is not declared.** This grades what is in `load-bearing.json`. A repository
nobody declared is invisible here and to every other class in the sweep. That is the reason the
declaration file exists and the reason it is reviewed.

**R2 credentials expire.** Then the pusher fails, the receipts stop being written, and this reports
BLIND on the receipts file rather than green on the last good day. That is the intended behaviour
and it is the difference between this drill and the one it replaced.
