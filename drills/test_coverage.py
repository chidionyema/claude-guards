#!/usr/bin/env python3
"""Paired control for coverage.py: it must say yes as well as no.

A gate tested only against the bad case is a gate nobody has proved is safe to
install. This estate learned that twice in one evening on 2026-08-23, when two
guards each refused correct work and four of six repositories could not push.
So every case below comes in pairs: the thing it must refuse, and the thing it
must let through.

The two REFUSE cases are the ones this file was actually written for, because
both had already happened by the time it existed:

  dead rule    A rule keyed on a remote starting `github.com/` matched zero of
               20 repositories, because every remote recorded starts
               `https://github.com/`. Nothing complained -- the rows came out
               unclassified alongside the ones that are meant to be.
  stale list   Coverage read from an old asset list is confident about assets
               that are gone and silent about ones that arrived. It has to
               report UNKNOWN, which is not the same as zero.

Run it: python3 drills/test_coverage.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COV = os.path.join(HERE, "coverage.py")


def stamp(hours_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",
                         time.gmtime(time.time() - hours_ago * 3600))


def run(inventory, coverage=None, args=()):
    """Run coverage.py against a made-up estate. Returns (exit code, output)."""
    with tempfile.TemporaryDirectory() as tmp:
        inv_path = os.path.join(tmp, "inventory.json")
        if inventory is not None:
            with open(inv_path, "w") as fh:
                json.dump(inventory, fh)
        env = dict(os.environ, ESTATE_INVENTORY=inv_path)
        cmd = [sys.executable, COV]
        if coverage is not None:
            # coverage.py reads its rules from beside itself, so a case that
            # needs different rules gets a whole scratch copy of the directory.
            scratch = os.path.join(tmp, "drills")
            os.makedirs(scratch)
            for name in ("coverage.py", "register.json"):
                with open(os.path.join(HERE, name)) as src, \
                     open(os.path.join(scratch, name), "w") as dst:
                    dst.write(src.read())
            with open(os.path.join(scratch, "coverage.json"), "w") as fh:
                json.dump(coverage, fh)
            cmd = [sys.executable, os.path.join(scratch, "coverage.py")]
        p = subprocess.run(cmd + list(args), env=env, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


# One job that every rule in the real coverage.json can classify: it restarts
# under recovery-posture, jobs.json can re-render it, and it has a vendor.
GOOD_JOB = {"id": "ai.estate.drills", "kind": "scheduled_job",
            "coupling": "anthropic", "loaded": True, "root": "~/.claude"}
# The same job with a coupling no rule covers, so its replace slot is nobody's.
BAD_JOB = dict(GOOD_JOB, id="ai.estate.invented", coupling="a-vendor-nobody-classified")

CASES = []


def case(name, want_exit, want_text, inventory, coverage=None, args=()):
    CASES.append((name, want_exit, want_text, inventory, coverage, args))


# --- ALLOW: the gate must not refuse work that is properly classified --------
case("allows a fully classified estate", 0, "Nothing on this estate is unaccounted for",
     {"at": stamp(1), "rows": [GOOD_JOB]})

case("allows an estate of only drills, which are not assets to drill", 0,
     "not an asset to drill",
     {"at": stamp(1), "rows": [{"id": "rebuild", "kind": "drill"}]})

case("allows an empty estate rather than inventing a problem", 0,
     "Nothing on this estate is unaccounted for", {"at": stamp(1), "rows": []})

# --- REFUSE: each of these has to be caught ---------------------------------
case("refuses an asset nobody classified", 1, "ai.estate.invented",
     {"at": stamp(1), "rows": [BAD_JOB]})

case("refuses a stale asset list instead of reporting green on it", 1,
     "past the 48h bar", {"at": stamp(200), "rows": [GOOD_JOB]})

case("refuses a missing asset list, because unknown is not zero", 1,
     "which is not the same as zero", None)

case("refuses an asset list with no generation stamp", 1, "carries no generation stamp",
     {"rows": [GOOD_JOB]})

case("refuses a kind it has never been taught about", 1,
     "never been taught about",
     {"at": stamp(1), "rows": [{"id": "a-thing", "kind": "kubernetes_cluster"}]})

# The bug exactly as it happened: the only rule deciding repo/replace is keyed
# on a prefix no remote actually starts with, so 20 repositories fall through.
# Four repositories rather than one, because below MIN_POPULATION the check
# keeps quiet on purpose -- one row missing every rule is not evidence of a typo.
case("refuses a rule that matches nothing, the GitHub prefix bug", 1,
     "repo/replace",
     {"at": stamp(1), "rows": [
         {"id": f"repo-{n}", "kind": "repo", "offsite": True,
          "remote": f"https://github.com/chidionyema/r{n}.git"} for n in range(4)]},
     {"rules": [{"name": "bundle", "kind": "repo", "when": {"offsite": True},
                 "rebuild": {"covered_by": "estate-bundle-restore"}},
                {"name": "github-gone, keyed on a prefix no remote has",
                 "kind": "repo", "when": {"remote": {"prefix": "github.com/"}},
                 "replace": {"covered_by": "github-gone"}}]})

# The sibling case the first version of the dead-rule check got wrong: two rules
# split one population, only one can match a given row, and neither is broken.
case("allows a rule pair where only one half matches this estate", 0,
     "Nothing on this estate is unaccounted for",
     {"at": stamp(1), "rows": [GOOD_JOB]},
     {"rules": [{"name": "restart", "kind": "scheduled_job", "when": {},
                 "restart": {"covered_by": "recovery-posture"}},
                {"name": "rebuild", "kind": "scheduled_job", "when": {},
                 "rebuild": {"covered_by": "rebuild"}},
                {"name": "has a vendor", "kind": "scheduled_job",
                 "when": {"coupling": "anthropic"},
                 "replace": {"covered_by": "no-anthropic"}},
                {"name": "has no vendor", "kind": "scheduled_job",
                 "when": {"coupling": "none"},
                 "replace": {"dismissed": "nothing external runs it"}}]})

# --gate splits the two failures the report carries. A hole in the estate is a
# number that has to fall; a broken answer key makes every number here a lie.
case("--gate lets an estate with holes in it through, because that number is "
     "reported and not gated", 0, "asset slot(s) nobody has classified",
     {"at": stamp(1), "rows": [BAD_JOB]}, None, ("--gate",))

case("--gate still refuses a broken answer key", 1, "not a drill on the register",
     {"at": stamp(1), "rows": [GOOD_JOB]},
     {"rules": [{"name": "restart", "kind": "scheduled_job", "when": {},
                 "restart": {"covered_by": "a-drill-that-does-not-exist"}},
                {"name": "rebuild", "kind": "scheduled_job", "when": {},
                 "rebuild": {"covered_by": "rebuild"}},
                {"name": "replace", "kind": "scheduled_job", "when": {},
                 "replace": {"covered_by": "no-anthropic"}}]},
     ("--gate",))

case("refuses a drill name that is not on the register", 1,
     "not a drill on the register",
     {"at": stamp(1), "rows": [GOOD_JOB]},
     {"rules": [{"name": "restart", "kind": "scheduled_job", "when": {},
                 "restart": {"covered_by": "a-drill-that-does-not-exist"}},
                {"name": "rebuild", "kind": "scheduled_job", "when": {},
                 "rebuild": {"covered_by": "rebuild"}},
                {"name": "replace", "kind": "scheduled_job", "when": {},
                 "replace": {"covered_by": "no-anthropic"}}]})


def main():
    passed = failed = 0
    for name, want_exit, want_text, inventory, coverage, args in CASES:
        code, out = run(inventory, coverage, args)
        ok = code == want_exit and want_text in out
        verdict = "yes " if want_exit == 0 else "NO  "
        if ok:
            passed += 1
            print(f"  pass  [{verdict}] {name}")
        else:
            failed += 1
            print(f"  FAIL  [{verdict}] {name}")
            print(f"        wanted exit {want_exit} and text {want_text!r}, "
                  f"got exit {code}")
            print("        " + "\n        ".join(out.strip().splitlines()[:8]))

    allow = sum(1 for c in CASES if c[1] == 0)
    print(f"\n{passed}/{len(CASES)} passed: {allow} that must be ALLOWED, "
          f"{len(CASES) - allow} that must be REFUSED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
