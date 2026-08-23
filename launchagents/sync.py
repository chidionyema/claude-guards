#!/usr/bin/env python3
"""Keep the committed copy of ~/Library/LaunchAgents honest.

--check  exits 1 when the live directory and this one differ. Meant for CI and
         for any agent about to trust the committed copy.
--pull   copies the live files in here so the difference can be committed.

Why this exists: a scheduled job could be added, edited or deleted on this Mac
and leave no record anywhere. The only trace of one such edit was a chat
transcript. This makes the difference visible as a failing command.
"""
import argparse, filecmp, os, shutil, sys

LIVE = os.path.expanduser("~/Library/LaunchAgents")
HERE = os.path.dirname(os.path.abspath(__file__))


def plists(d):
    return {f for f in os.listdir(d) if f.endswith(".plist")} if os.path.isdir(d) else set()


def compare():
    live, here = plists(LIVE), plists(HERE)
    return (sorted(live - here),            # on the machine, not committed
            sorted(here - live),            # committed, gone from the machine
            sorted(f for f in live & here   # in both, different content
                   if not filecmp.cmp(os.path.join(LIVE, f), os.path.join(HERE, f), shallow=False)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--pull", action="store_true")
    a = ap.parse_args()

    uncommitted, deleted, changed = compare()

    if a.pull:
        for f in uncommitted + changed:
            shutil.copy2(os.path.join(LIVE, f), os.path.join(HERE, f))
        for f in deleted:
            os.remove(os.path.join(HERE, f))
        print(f"pulled: {len(uncommitted)} new, {len(changed)} changed, {len(deleted)} removed")
        print("commit this directory to record it")
        return 0

    for label, group in (("on the machine, never committed", uncommitted),
                         ("committed, no longer on the machine", deleted),
                         ("committed copy differs from the live file", changed)):
        if group:
            print(f"{label}: {len(group)}")
            for f in group:
                print(f"    {f}")

    if not (uncommitted or deleted or changed):
        print(f"in step: {len(plists(LIVE))} plists identical in both places")
        return 0

    if a.check:
        print("\nrun `python3 launchagents/sync.py --pull` then commit.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
