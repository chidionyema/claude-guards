#!/usr/bin/env python3
"""Assert the newest estate bundle was cloned back after it was uploaded.

estate_bundle_push.sh uploads a git bundle and then clones it again, writing
"restore":"verify-ok" into its receipt. That is the real assertion; this file
only checks that the newest receipt carries it and is recent. A push script that
died last week still leaves last week's green receipt sitting there, so the age
is half the check.
"""
import json
import os
import re
import sys
import time

RECEIPTS = os.path.expanduser("~/.claude/state/estate-bundle-push.jsonl")
MAX_AGE_HOURS = 48
#: A lock held longer than this is a wedged pusher, not a busy one. The hourly job
#: takes about 20 seconds when it works; on 2026-08-23 one copy held the lock for
#: 4586 seconds and three runs in a row skipped behind it.
WEDGED_SECONDS = 3600


def main():
    if not os.path.exists(RECEIPTS):
        print(f"no receipts at {RECEIPTS}: nothing has ever been pushed")
        return 1

    with open(RECEIPTS) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    if not rows:
        print("the receipts file is empty")
        return 1

    # The newest ATTEMPT, not the newest row. A skip row carries a timestamp and no
    # verdict, so taking it as the newest reads as a push that proved nothing and,
    # worse, resets the age clock: a pusher wedged for two days would look fresh
    # because it kept writing skips the whole time.
    tried = [r for r in rows if r.get("event") != "skipped"]
    if not tried:
        print(f"{len(rows)} receipts and not one push attempt among them")
        return 1
    newest = max(tried, key=lambda r: r.get("ts", 0))
    age_h = (time.time() - newest.get("ts", 0)) / 3600
    verdict = newest.get("restore")
    print(f"newest receipt  {newest.get('iso')}  {newest.get('slug')}  "
          f"restore={verdict}  age={age_h:.1f}h")

    # Two of the three values are passes and they are not equally strong.
    # clone-ok means a full bundle was downloaded and cloned standalone, which is
    # a real restore. verify-ok means an incremental bundle was verified AGAINST
    # THIS REPO, which stops meaning anything the moment this Mac is gone.
    # Anything else is a push that produced a receipt and no proof.
    window = rows[-20:]

    # A skip is not a failed push. estate_bundle_push.sh writes {"event":"skipped"}
    # when another copy of itself already holds the lock, and that row carries no
    # slug and no restore verdict because no push was attempted. Counting those as
    # "proved nothing" turned the drill red on 2026-08-23 while every real push in
    # the window had passed, which is a checker that cries about its own healthy
    # concurrency control.
    skipped = [r for r in window if r.get("event") == "skipped"]
    attempts = [r for r in window if r.get("event") != "skipped"]
    bad = [r for r in attempts if r.get("restore") not in ("clone-ok", "verify-ok")]
    if bad:
        print(f"{len(bad)} of the last {len(attempts)} pushes proved nothing:")
        for r in bad[:5]:
            print(f"  {r.get('iso')}  {r.get('slug')}  restore={r.get('restore')}")
        return 1

    # The skips still carry news, and it is the one thing they can say: how long
    # the lock was held. A push that has been waiting on a lock for over an hour is
    # a wedged pusher, and the estate would otherwise learn that only when the age
    # check below finally trips, hours later.
    if skipped:
        longest = max((r.get("reason", "") for r in skipped),
                      key=lambda s: int(re.search(r"(\d+)s", s).group(1))
                      if re.search(r"(\d+)s", s) else 0)
        held = re.search(r"(\d+)s", longest)
        print(f"  {len(skipped)} of the last {len(window)} runs skipped on a held lock; "
              f"longest wait {int(held.group(1)) // 60 if held else 0} min")
        # A wedge that a later push cleared is history, not a fault. Firing on the
        # scar would leave the drill red for the twenty runs it takes the window to
        # roll past, and a check that stays red after the thing recovered is one
        # people learn to ignore. Fail only while nothing has succeeded since.
        if held and int(held.group(1)) > WEDGED_SECONDS:
            worst_ts = max(r.get("ts", 0) for r in skipped
                           if r.get("reason", "") == longest)
            recovered = [r for r in attempts if r.get("ts", 0) > worst_ts
                         and r.get("restore") in ("clone-ok", "verify-ok")]
            if recovered:
                print(f"  that wedge cleared: {newest.get('iso')} pushed "
                      f"{age_h:.1f}h ago, after it")
            else:
                print(f"the bundle pusher has held its lock for "
                      f"{int(held.group(1)) // 60} minutes and nothing has pushed "
                      f"since: {longest}")
                return 1
    if not attempts:
        print(f"all {len(window)} recent runs skipped; nothing has been pushed at all")
        return 1
    if age_h > MAX_AGE_HOURS:
        print(f"nothing has been pushed for {age_h:.0f}h, over the {MAX_AGE_HOURS}h bar")
        return 1

    standalone = [r for r in attempts if r.get("restore") == "clone-ok"]
    if not standalone:
        print(f"all {len(attempts)} recent pushes are incremental, verified against this "
              f"Mac. No bundle has been cloned standalone, so the offsite copy has "
              f"never been proved to stand on its own.")
        return 1

    print(f"{len(standalone)} of the last {len(attempts)} pushes cloned back standalone, "
          f"newest push {age_h:.1f}h ago")
    return 0


if __name__ == "__main__":
    sys.exit(main())
