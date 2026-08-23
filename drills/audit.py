#!/usr/bin/env python3
"""Discover what this estate depends on, and refuse anything nobody has classified.

WHY THIS IS A SCRIPT AND NOT A DOCUMENT. The list of things that can be taken
away from this company changes every time somebody adds an API call. A document
saying "we depend on X, Y and Z" is true on the day it is written and quietly
wrong a week later, and nothing tells you which week. This reads the tree.

WHAT IT ENFORCES. Every external host and every credential name found in the
tree must appear in dependencies.json as EXACTLY one of two things:

    covered_by: <drill id>   something proves we survive losing it
    dismissed:  <reason>     a person decided it cannot stop us, and said why

There is no third state. An unclassified dependency is not a small problem, it
is the only kind of problem this file exists to find: a vendor that arrived
without anybody deciding what happens when it leaves.

HOW IT ENFORCES. `--ci` reads only the tree, so it runs on a GitHub runner with
no credentials and no network. Adding a new vendor to a pull request without
classifying it fails the pull request. That is the whole mechanism -- the
register cannot rot, because rot is a red check.

WHAT IT DOES NOT DO. It does not decide whether a dismissal is honest. A person
writing "dismissed: don't care" passes this check. It closes the gap where a
dependency arrives and nobody notices at all, which is the gap that produced 33
hosts and 19 credential names that had never once been listed in one place.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEPS = os.path.join(HERE, "dependencies.json")
REGISTER = os.path.join(HERE, "register.json")

HOST = re.compile(rb"https?://([a-zA-Z0-9.-]+\.[a-z]{2,})")
CRED = re.compile(rb"\b([A-Z][A-Z0-9]*_(?:API_KEY|TOKEN|SECRET|KEY|ACCOUNT_ID|PASSWORD))\b")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
# This file names every host and credential in the estate by design, and
# dependencies.json is the answer key. Reading either as evidence would make the
# audit pass by quoting itself.
SKIP_FILES = {"audit.py", "dependencies.json"}


def discover():
    hosts, creds = set(), set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES or fn.endswith((".pyc", ".png", ".jpg", ".gz", ".zip")):
                continue
            try:
                with open(os.path.join(dirpath, fn), "rb") as fh:
                    blob = fh.read(2_000_000)
            except OSError:
                continue
            hosts.update(m.decode() for m in HOST.findall(blob))
            creds.update(m.decode() for m in CRED.findall(blob))
    return hosts, creds


def drill_ids():
    reg = json.load(open(REGISTER))
    live = {d["id"] for d in reg["drills"]}
    return live, {d["id"]: bool(d.get("cmd")) for d in reg["drills"]}


def check(kind, found, table, live):
    """(unclassified, pointing at a drill that does not exist, both states, neither)"""
    problems = []
    for name in sorted(found):
        e = table.get(name)
        if e is None:
            problems.append((name, "not classified: it is neither drilled nor dismissed"))
            continue
        cov, dis = e.get("covered_by"), e.get("dismissed")
        if cov and dis:
            problems.append((name, "both covered_by and dismissed; pick one"))
        elif not cov and not dis:
            problems.append((name, "classified with neither covered_by nor dismissed"))
        elif cov and cov not in live:
            problems.append((name, f"covered_by names '{cov}', which is not a drill on the register"))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ci", action="store_true",
                    help="tree only, no network, no board post; the pull request gate")
    a = ap.parse_args()

    hosts, creds = discover()
    table = json.load(open(DEPS))
    live, written = drill_ids()

    problems = ([("host " + n, w) for n, w in check("host", hosts, table["hosts"], live)]
                + [("credential " + n, w) for n, w in check("credential", creds, table["credentials"], live)])

    covered = [n for n, e in list(table["hosts"].items()) + list(table["credentials"].items())
               if e.get("covered_by")]
    # A dependency pointing at a drill nobody has written is covered on paper only.
    onpaper = sorted({e["covered_by"] for e in list(table["hosts"].values()) + list(table["credentials"].values())
                      if e.get("covered_by") and not written.get(e["covered_by"], False)})

    print(f"{len(hosts)} hosts and {len(creds)} credential names in the tree")
    print(f"{len(covered)} point at a drill, {len(hosts) + len(creds) - len(covered)} are dismissed with a reason")
    if onpaper:
        print("\ncovered on paper only, because these drills are NOT WRITTEN:")
        for d in onpaper:
            names = [n for n, e in list(table["hosts"].items()) + list(table["credentials"].items())
                     if e.get("covered_by") == d]
            print(f"  {d:<24} {len(names)} dependencies rest on it: {', '.join(names[:5])}")

    if problems:
        print(f"\n{len(problems)} unclassified:")
        for n, w in problems:
            print(f"  {n}: {w}")
        print("\nAdd each to drills/dependencies.json with covered_by or dismissed.")
        return 1

    print("\nnothing unclassified")
    if not a.ci:
        try:
            sys.path.insert(0, ROOT)
            import tracked
            tracked.board("dependency-audit",
                          f"Dependency audit: {len(hosts)} hosts and {len(creds)} credential names, "
                          f"0 unclassified. {len(onpaper)} drills are named as cover and not written: "
                          + (", ".join(onpaper) or "none") + ".", "drills")
        except Exception as e:
            print(f"board post failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
