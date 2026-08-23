#!/usr/bin/env python3
"""Drill: can the keys that decrypt everything be recovered without this laptop?

The escrow is two halves in two accounts -- ciphertext in Cloudflare R2, the key
that opens it in iCloud Drive. This drill is the half that keeps the other one
honest. It does what a rebuild on a new machine would do: fetch the blob, open
it with the iCloud key, and then use what came out against ciphertext the escrow
has never touched.

Sealing and verifying are deliberately separate jobs. If the drill re-sealed
whatever it found missing it could never go red, which is the exact shape LAW 28
calls a lie with a cron schedule: a copy that repairs itself on inspection
reports health it has not got. So the daily job seals and this weekly drill
reads, and when the sealer dies the drill notices within a week.
"""
import os
import subprocess
import sys

ESCROW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "estate", "key_escrow.py")


def main():
    if not os.path.exists(ESCROW):
        print("DRILL FAILED: no escrow script at %s" % ESCROW)
        return 1
    p = subprocess.run([sys.executable, ESCROW, "--verify"],
                       capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    print(out if out else "(the escrow script said nothing)")
    if p.returncode != 0:
        print("DRILL FAILED: the two age keys and the R2 credentials cannot be "
              "recovered without this laptop.")
        return 1
    print("DRILL PASSED: a new machine with the founder's Apple ID and his "
          "Cloudflare account can recover both age keys.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
