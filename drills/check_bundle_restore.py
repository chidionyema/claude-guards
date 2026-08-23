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
import sys
import time

RECEIPTS = os.path.expanduser("~/.claude/state/estate-bundle-push.jsonl")
MAX_AGE_HOURS = 48


def main():
    if not os.path.exists(RECEIPTS):
        print(f"no receipts at {RECEIPTS}: nothing has ever been pushed")
        return 1

    with open(RECEIPTS) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    if not rows:
        print("the receipts file is empty")
        return 1

    newest = max(rows, key=lambda r: r.get("ts", 0))
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
    bad = [r for r in window if r.get("restore") not in ("clone-ok", "verify-ok")]
    if bad:
        print(f"{len(bad)} of the last {len(window)} pushes proved nothing:")
        for r in bad[:5]:
            print(f"  {r.get('iso')}  {r.get('slug')}  restore={r.get('restore')}")
        return 1
    if age_h > MAX_AGE_HOURS:
        print(f"nothing has been pushed for {age_h:.0f}h, over the {MAX_AGE_HOURS}h bar")
        return 1

    standalone = [r for r in window if r.get("restore") == "clone-ok"]
    if not standalone:
        print(f"all {len(window)} recent pushes are incremental, verified against this "
              f"Mac. No bundle has been cloned standalone, so the offsite copy has "
              f"never been proved to stand on its own.")
        return 1

    print(f"{len(standalone)} of the last {len(window)} pushes cloned back standalone, "
          f"newest push {age_h:.1f}h ago")
    return 0


if __name__ == "__main__":
    sys.exit(main())
