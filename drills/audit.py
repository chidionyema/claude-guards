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
import fnmatch
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUARDS = os.path.dirname(HERE)          # the claude-guards checkout this file lives in
ROOT = GUARDS
DEPS = os.path.join(HERE, "dependencies.json")
REGISTER = os.path.join(HERE, "register.json")
REPOS = os.path.join(HERE, "repos.json")

HOST = re.compile(rb"https?://([a-zA-Z0-9.-]+\.[a-z]{2,})")
CRED = re.compile(rb"\b([A-Z][A-Z0-9]*_(?:API_KEY|TOKEN|SECRET|KEY|ACCOUNT_ID|PASSWORD))\b")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
BINARY = (".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".gz",
          ".zip", ".tar", ".woff", ".woff2", ".ttf", ".so", ".dylib")


def discover(root, deps_path, exclude):
    """Every host and credential name in `root`, minus what cannot be evidence.

    Three things are never read, and each for a different reason. The auditor's
    own checkout, because a file whose job is to name every host names every
    host. The answer key, because a check that reads its own answers passes by
    quoting itself. And whatever the answer key's `scan.exclude` names, because
    a repository can hold records as well as code -- claude-estate tracks 1586
    conversation transcripts, and a URL somebody pasted into one is not a vendor
    this company took on.

    That last one is also the way this gate would be neutered: exclude the
    directory the new vendor landed in and the check goes green. So the count it
    removed is printed on every run, in the pull request, where a person reading
    the check sees the number grow.
    """
    hosts, creds, skipped = set(), set(), 0
    root = os.path.abspath(root)
    deps_path = os.path.abspath(deps_path)
    # When another repository is being audited, the auditor rides along as a
    # checkout inside that repository's workspace. Its own tree is not that
    # repository's dependencies. When claude-guards audits itself, root IS the
    # guards checkout and there is nothing to subtract.
    riding_along = GUARDS != root and GUARDS.startswith(root + os.sep)

    # Read the git index, not the working tree. A runner checks out tracked
    # files and nothing else, so a walk of a developer's directory reads build
    # output, virtualenvs and scratch files that CI will never see -- and the
    # two readings then disagree for a reason that has nothing to do with
    # dependencies. Asking git makes the local answer and the pull request's
    # answer the same measurement (LAW 15).
    tracked = None
    try:
        p = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                           capture_output=True, timeout=120)
        if p.returncode == 0:
            tracked = {os.path.join(root, f.decode())
                       for f in p.stdout.split(b"\0") if f}
    except (OSError, subprocess.SubprocessError):
        tracked = None

    def consider(full):
        nonlocal skipped
        rel = os.path.relpath(full, root)
        if full == deps_path or os.path.basename(full) == "audit.py" or full.endswith(BINARY):
            return
        if riding_along and (full == GUARDS or full.startswith(GUARDS + os.sep)):
            return
        if any(fnmatch.fnmatch(rel, pat) or rel.startswith(pat.rstrip("/") + "/")
               for pat in exclude):
            skipped += 1
            return
        try:
            with open(full, "rb") as fh:
                blob = fh.read(2_000_000)
        except OSError:
            return
        hosts.update(m.decode() for m in HOST.findall(blob))
        creds.update(m.decode() for m in CRED.findall(blob))

    if tracked is not None:
        # Walking is pointless once git has named the files: ~/.claude holds
        # 1658 tracked files inside a directory tree of millions, and os.walk
        # pays for the tree.
        for full in tracked:
            consider(full)
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            here = os.path.abspath(dirpath)
            if riding_along and (here == GUARDS or here.startswith(GUARDS + os.sep)):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                consider(os.path.join(dirpath, fn))

    return hosts, creds, skipped


def drill_ids(register):
    reg = json.load(open(register))
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


def sweep(ci):
    """Audit every repository, including the ones GitHub will not run a job for.

    Four of the six repositories are public and the gate runs on their pull
    requests. Two are private, and Actions refuses to start a job on this
    account's private repositories -- the annotation is verbatim "The job was
    not started because recent account payments have failed or your spending
    limit needs to be increased". A gate that cannot run on two repositories is
    not a gate on those two, so they are read here instead. That is detection
    rather than enforcement, and the difference is named in the output rather
    than glossed over.
    """
    home = os.path.expanduser("~")
    repos = json.load(open(REPOS))["repos"]
    lines, bad = [], 0
    for r in repos:
        root = r["root"].replace("{HOME}", home)
        deps = os.path.join(root, r["deps"])
        if not os.path.isdir(root):
            lines.append(f"  {r['name']:<16} MISSING     no checkout at {root}")
            bad += 1
            continue
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--ci",
                            "--root", root, "--deps", deps],
                           capture_output=True, text=True)
        head = (p.stdout.strip().splitlines() or [""])[0]
        counts = head.split(": ", 1)[-1] if ": " in head else head
        how = "PR gate" if r.get("ci") else "here only"
        if p.returncode == 0:
            lines.append(f"  {r['name']:<16} clean       {counts}   [{how}]")
        else:
            bad += 1
            unc = [l.strip() for l in p.stdout.splitlines() if ": not classified" in l
                   or ": both " in l or ": classified with" in l or "which is not a drill" in l]
            lines.append(f"  {r['name']:<16} UNCLASSIFIED  {counts}   [{how}]")
            lines.extend("      " + u for u in unc)

    enforced = sum(1 for r in repos if r.get("ci"))
    print(f"{len(repos)} repositories, {enforced} with the gate on their pull requests, "
          f"{len(repos) - enforced} readable only here")
    print("\n".join(lines))
    for r in repos:
        if r.get("no_ci_because"):
            print(f"\n  {r['name']}: {r['no_ci_because']}")

    if not ci:
        try:
            sys.path.insert(0, GUARDS)
            import tracked
            tracked.board("dependency-audit",
                          f"Dependency audit swept {len(repos)} repositories: "
                          + (f"{bad} with something unclassified." if bad
                             else "every host and credential is drilled or dismissed.")
                          + f" {enforced} of {len(repos)} are enforced on pull requests; the rest are private "
                            "and Actions will not start a job on them.", "drills")
        except Exception as e:
            print(f"board post failed: {e}", file=sys.stderr)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description="Every dependency is drilled or dismissed.")
    ap.add_argument("--ci", action="store_true",
                    help="tree only, no network, no board post; the pull request gate")
    ap.add_argument("--root", default=ROOT,
                    help="the tree to read (default: the claude-guards checkout this file lives in)")
    ap.add_argument("--deps", default=DEPS,
                    help="the answer key for that tree (default: drills/dependencies.json)")
    ap.add_argument("--register", default=REGISTER,
                    help="the drill register every covered_by must name (default: drills/register.json)")
    ap.add_argument("--sweep", action="store_true",
                    help="audit every repository in repos.json; the answer for the ones CI cannot reach")
    ap.add_argument("--list", action="store_true",
                    help="print what is in the tree and exit 0; for writing an answer key")
    a = ap.parse_args()

    if a.sweep:
        return sweep(a.ci)

    if not os.path.exists(a.deps):
        # A missing answer key is the one failure that must not read as clean.
        # The repository has dependencies whether or not anybody wrote them down.
        if not a.list:
            print(f"no answer key at {a.deps}", file=sys.stderr)
            print("Every repository that runs this gate carries one. Write it with --list.",
                  file=sys.stderr)
            return 1
        table = {"scan": {"exclude": []}, "hosts": {}, "credentials": {}}
    else:
        table = json.load(open(a.deps))
    exclude = table.get("scan", {}).get("exclude", [])

    hosts, creds, skipped = discover(a.root, a.deps, exclude)

    if a.list:
        for h in sorted(hosts):
            print("host       " + h)
        for c in sorted(creds):
            print("credential " + c)
        return 0

    live, written = drill_ids(a.register)
    problems = ([("host " + n, w) for n, w in check("host", hosts, table["hosts"], live)]
                + [("credential " + n, w) for n, w in check("credential", creds, table["credentials"], live)])

    entries = list(table["hosts"].items()) + list(table["credentials"].items())
    covered = [n for n, e in entries if e.get("covered_by")]
    # A dependency pointing at a drill nobody has written is covered on paper only.
    onpaper = sorted({e["covered_by"] for _, e in entries
                      if e.get("covered_by") and not written.get(e["covered_by"], False)})

    print(f"{os.path.basename(os.path.abspath(a.root))}: "
          f"{len(hosts)} hosts and {len(creds)} credential names in the tree")
    print(f"{len(covered)} point at a drill, {len(hosts) + len(creds) - len(covered)} are dismissed with a reason")
    if exclude:
        # Printed every run, not only when it changes: this line is how a person
        # reading the check sees the gate being narrowed.
        print(f"{skipped} files not read, because the answer key excludes: {', '.join(exclude)}")
    if onpaper:
        print("\ncovered on paper only, because these drills are NOT WRITTEN:")
        for d in onpaper:
            names = [n for n, e in entries if e.get("covered_by") == d]
            print(f"  {d:<24} {len(names)} dependencies rest on it: {', '.join(names[:5])}")

    if problems:
        print(f"\n{len(problems)} unclassified:")
        for n, w in problems:
            print(f"  {n}: {w}")
        print(f"\nAdd each to {a.deps} with covered_by or dismissed.")
        return 1

    print("\nnothing unclassified")
    if not a.ci:
        try:
            sys.path.insert(0, GUARDS)
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
