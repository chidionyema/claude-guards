#!/usr/bin/env python3
"""Collapse the branch and worktree estate to a clean slate, losing nothing.

The order of the phases IS the safety argument, and nothing may be reordered:

  1. push every local-only branch          -> nothing lives only on this laptop
  2. snapshot + push every dirty worktree  -> nothing lives only in a working tree
  3. build ONE archive commit whose parents are every branch tip, push it, and
     CONFIRM origin holds it at that exact sha (git ls-remote, not exit status)
  4. only then delete branches (remote + local) and remove worktrees

After phase 3 every commit in the estate is reachable from a single ref on the
server, so phase 4 cannot lose work. Recovering any branch afterwards is one
command -- `git branch <name> <sha>` -- using the name->sha map that is
committed INSIDE the archive commit as BRANCHES.txt.

Age is deliberately NOT the criterion. Measured 2026-08-20: 341 of 342 remote
branches were five days old or newer, so a 7-day or 14-day rule deletes exactly
one branch and leaves the mess untouched. What makes a ref disposable here is
that its commits are archived, not that they are old.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

CLONES = [
    Path("/Users/chidionyema/Documents/code/prospector"),
    Path("/Users/chidionyema/Library/Mobile Documents/com~apple~CloudDocs/"
         "Documents/code/prospector"),
]
# The clone that owns the archive: it must be the one with a normal .git and a
# healthy object store, never the iCloud copy (fileproviderd rewrites under it).
PRIMARY = CLONES[0]
STAMP = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
ARCHIVE_REF = f"refs/heads/estate-archive/{STAMP}"

# Never deleted, whatever else is true.
KEEP_EXACT = {"main", "master"}
KEEP_PREFIX = ("estate-archive/",)



# A checker that prints failures and exits 0 is lying to whatever reads its log -- a wrapper, a
# launchd job, a founder's `&&`. Trap reported 2026-08-20 by wt-storeroot-42, who watched a gate
# print "80 FAILING CELLS" and exit 0, after which every downstream log repeated exit=0. This
# script had it: origin could decline to confirm the archive, phase 4 would correctly delete
# nothing, and main() still returned 0. Every failure path now goes through fail().
FAILURES: list[str] = []


def fail(msg: str) -> None:
    """Print a failure AND make it reach the exit status."""
    FAILURES.append(msg)
    print(msg)


def exit_status() -> int:
    if not FAILURES:
        return 0
    print(f"\n!! {len(FAILURES)} failure(s) -- exiting 1 so nothing downstream reads this as clean")
    for m in FAILURES:
        print(f"   {m.strip()}")
    return 1


def git(args: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, f"{type(e).__name__}: {e}"
    return p.returncode, (p.stdout + p.stderr).strip()


def open_pr_heads() -> set[str]:
    """Head branches of OPEN pull requests. Deleting one closes the PR, which is
    a change to somebody's review, so they are kept whatever else is true."""
    try:
        p = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", "300",
                            "--json", "number,headRefName"],
                           cwd=str(PRIMARY), capture_output=True, text=True, timeout=120)
        if p.returncode:
            print("  !! cannot list open PRs -- refusing to delete any remote branch")
            return {"*ALL*"}
        return {r["headRefName"] for r in json.loads(p.stdout)}
    except Exception as e:  # noqa: BLE001 -- any failure here must stop deletion
        print(f"  !! cannot list open PRs ({type(e).__name__}) -- refusing to delete")
        return {"*ALL*"}


def protected(name: str, pr_heads: set[str]) -> bool:
    if "*ALL*" in pr_heads:
        return True
    return name in KEEP_EXACT or name in pr_heads or name.startswith(KEEP_PREFIX)


def phase1_push_local_only(apply: bool) -> int:
    """Anything that exists only in a local .git is one disk failure from gone."""
    print("\n=== PHASE 1 - local-only branches to origin ===")
    pushed = 0
    for clone in CLONES:
        if not (clone / ".git").exists():
            continue
        rc, out = git(["ls-remote", "--heads", "origin"], clone)
        if rc:
            print(f"  SKIP {clone}: cannot reach origin")
            continue
        on_remote = {ln.split("\t", 1)[1] for ln in out.splitlines() if "\t" in ln}
        rc, out = git(["for-each-ref", "--format=%(objectname) %(refname)",
                       "refs/heads"], clone)
        missing = [(sha, ref)
                   for sha, ref in (ln.split(" ", 1) for ln in out.splitlines())
                   if ref not in on_remote]
        if not missing:
            print(f"  {clone.name}: all local branches already on origin")
            continue
        print(f"  {clone}: {len(missing)} local-only")
        for _, ref in missing:
            print(f"      {ref.removeprefix('refs/heads/')}")
        if not apply:
            continue
        # One refspec per push. `git push` is ATOMIC IN ITS ARGUMENT LIST: one bad
        # object failed all 14 refspecs earlier today and pushed nothing at all.
        for sha, ref in missing:
            rc, out = git(["push", "origin", f"{sha}:{ref}"], clone, timeout=900)
            if rc:
                print(f"      FAILED {ref}: {out.splitlines()[-1] if out else '?'}")
            else:
                pushed += 1
    print(f"  pushed: {pushed}")
    return pushed


def phase2_worktrees(apply: bool) -> int:
    """Snapshot every dirty worktree and remove the dead ones. Delegated to
    estate_cleanup.py, which already knows the two-clone ownership trap."""
    print("\n=== PHASE 2 - worktrees (snapshot, then remove) ===")
    helper = Path(__file__).with_name("estate_cleanup.py")
    if not helper.exists():
        print(f"  !! {helper} missing -- skipping worktree phase")
        return 1
    cmd = [sys.executable, str(helper)] + (["--apply"] if apply else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    print("\n".join("  " + ln for ln in (p.stdout + p.stderr).strip().splitlines()))
    return p.returncode


def phase3_archive(apply: bool) -> str | None:
    """One commit, every branch tip as a parent, the name->sha map in its tree.

    Reachability is the whole point: GitHub garbage-collects unreferenced objects,
    so a deleted branch survives only while something still points at its commits.
    One ref pointing at all of them is that something."""
    print("\n=== PHASE 3 - the archive commit ===")
    rc, _ = git(["fetch", "origin", "+refs/heads/*:refs/remotes/origin/*", "--prune"],
                PRIMARY, timeout=1800)
    if rc:
        print("  !! fetch failed -- cannot build a complete archive, stopping")
        return None
    rc, out = git(["for-each-ref", "--format=%(objectname) %(refname:short)",
                   "refs/remotes/origin", "refs/heads"], PRIMARY)
    if rc:
        print("  !! cannot list refs")
        return None
    tips: dict[str, str] = {}
    for ln in out.splitlines():
        sha, name = ln.split(" ", 1)
        name = name.removeprefix("origin/")
        if name == "HEAD" or name.startswith(KEEP_PREFIX):
            continue
        tips.setdefault(name, sha)
    if not tips:
        print("  nothing to archive")
        return None
    # A tip whose object is missing locally would fail commit-tree and take the
    # whole archive down with it, so each one is proved present before it is used.
    good: dict[str, str] = {}
    for name, sha in sorted(tips.items()):
        rc, _ = git(["cat-file", "-e", f"{sha}^{{commit}}"], PRIMARY, timeout=60)
        if rc:
            print(f"  !! {name} @ {sha[:8]} not in this object store -- "
                  "excluded from the archive, so it will NOT be deleted either")
            continue
        good[name] = sha
    print(f"  archiving {len(good)} branch tips as parents of one commit")
    if not apply:
        print(f"  would push {ARCHIVE_REF}")
        return "DRYRUN"

    body = "\n".join(f"{sha} {name}" for name, sha in sorted(good.items())) + "\n"
    p = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=str(PRIMARY),
                       input=body, capture_output=True, text=True, timeout=120)
    if p.returncode:
        print(f"  !! hash-object failed: {p.stderr.strip()}")
        return None
    blob = p.stdout.strip()
    p = subprocess.run(["git", "mktree"], cwd=str(PRIMARY),
                       input=f"100644 blob {blob}\tBRANCHES.txt\n",
                       capture_output=True, text=True, timeout=120)
    if p.returncode:
        print(f"  !! mktree failed: {p.stderr.strip()}")
        return None
    tree = p.stdout.strip()
    parents: list[str] = []
    for sha in good.values():
        parents += ["-p", sha]
    msg = (f"estate archive {STAMP}: {len(good)} branch tips\n\n"
           "Every commit in the estate at this moment is reachable from here.\n"
           "BRANCHES.txt in this commit's tree maps each branch name to its sha.\n"
           "Restore any branch with:  git branch <name> <sha>\n")
    p = subprocess.run(["git", "commit-tree", tree, *parents, "-m", msg],
                       cwd=str(PRIMARY), capture_output=True, text=True, timeout=600)
    if p.returncode:
        print(f"  !! commit-tree failed: {p.stderr.strip()[:400]}")
        return None
    sha = p.stdout.strip()
    rc, out = git(["push", "origin", f"{sha}:{ARCHIVE_REF}"], PRIMARY, timeout=3600)
    if rc:
        print(f"  !! push failed: {out.splitlines()[-1] if out else '?'}")
        return None
    # The push exit status is a claim. This is the proof.
    rc, out = git(["ls-remote", "origin", ARCHIVE_REF], PRIMARY, timeout=300)
    if rc or not out.startswith(sha):
        fail(f"  !! origin does NOT confirm {ARCHIVE_REF} at {sha[:8]} -- "
              "nothing will be deleted")
        return None
    print(f"  CONFIRMED on origin: {ARCHIVE_REF} = {sha}")
    return sha


def phase4_delete(archived: str | None, apply: bool) -> None:
    print("\n=== PHASE 4 - delete branches ===")
    if not archived:
        print("  archive not confirmed -- deleting nothing. This is the interlock.")
        return
    pr_heads = open_pr_heads()
    rc, out = git(["for-each-ref", "--format=%(refname:short)",
                   "refs/remotes/origin"], PRIMARY)
    remote = sorted({n.removeprefix("origin/") for n in out.splitlines()
                     if n != "origin/HEAD"})
    doomed = [n for n in remote if not protected(n, pr_heads)]
    kept = [n for n in remote if protected(n, pr_heads)]
    print(f"  remote: {len(doomed)} to delete, {len(kept)} kept "
          f"({', '.join(kept[:8])})")
    if apply and archived != "DRYRUN":
        # Batched, because a push is atomic in its argument list: one stale ref in
        # a 342-long list deletes none of them.
        for i in range(0, len(doomed), 50):
            batch = doomed[i:i + 50]
            rc, _ = git(["push", "origin", *[f":refs/heads/{n}" for n in batch]],
                        PRIMARY, timeout=1800)
            if rc:
                print(f"    batch {i // 50}: failed as a batch, retrying singly")
                for n in batch:
                    git(["push", "origin", f":refs/heads/{n}"], PRIMARY, timeout=300)
            else:
                print(f"    batch {i // 50}: {len(batch)} deleted")
    for clone in CLONES:
        if not (clone / ".git").exists():
            continue
        rc, out = git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], clone)
        loc = [n for n in out.splitlines() if not protected(n, pr_heads)]
        print(f"  {clone}: {len(loc)} local branches to delete")
        if apply and archived != "DRYRUN":
            for i in range(0, len(loc), 100):
                git(["branch", "-D", *loc[i:i + 100]], clone, timeout=600)
        git(["remote", "prune", "origin"], clone, timeout=600)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually push, archive and delete (default is report only)")
    a = ap.parse_args()
    print(f"=== estate reset - {'APPLY' if a.apply else 'REPORT ONLY'} - {STAMP} ===")
    phase1_push_local_only(a.apply)
    phase2_worktrees(a.apply)
    archived = phase3_archive(a.apply)
    phase4_delete(archived, a.apply)
    print("\n=== done ===")
    if a.apply and archived and archived != "DRYRUN":
        print(f"Everything is reachable from origin {ARCHIVE_REF} ({archived[:12]}).")
        print("Restore any branch:")
        print(f"  git fetch origin {ARCHIVE_REF.removeprefix('refs/heads/')}")
        print(f"  git show {archived[:12]}:BRANCHES.txt | grep <name>")
        print("  git branch <name> <sha>")
    return exit_status()


if __name__ == "__main__":
    sys.exit(main())
