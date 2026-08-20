#!/usr/bin/env python3
"""Delete dead worktrees and branches, and never lose work doing it.

THE ORDER IS THE WHOLE DESIGN. Nothing is deleted until origin has confirmed, in its own
words, that it holds the work. Not "the push exited 0" -- `git ls-remote` naming the ref at
the sha we pushed. A push that reports success and a server that has the ref are different
claims, and only the second one is a reason to delete a directory.

THREE DEFECTS THIS EXISTS TO SURVIVE, all measured on 2026-08-20:

1. A WORKTREE IS NOT OWNED BY THE CLONE THAT LISTS IT. Two clones on this machine share an
   origin and cross-register each other's worktrees: `git worktree list` in the main checkout
   names trees whose `.git` file points into the iCloud clone. `git worktree remove` then
   fails with "does not point back to .git/worktrees/<name>", and `git push` of a snapshot
   taken there fails with "fatal: bad object". Every operation here is routed to the clone
   the tree's own `.git` file names, never to the clone that happened to list it.

2. `git push` IS ATOMIC IN ITS ARGUMENT LIST. One unresolvable sha fails every refspec beside
   it. A run over the iCloud clone lost all 14 snapshots to one bad object. Refspecs are
   therefore grouped by owning object store and pushed once per store, and a failed group
   never blocks the others.

3. AN AGENT SESSION HOLDS NO PROCESS. A session between tool calls has nothing in `lsof`, so
   "no process is in this directory" does not mean "nobody is working here". THREE tests run
   and ANY of them keeps the tree: a process holding a file open anywhere inside it; a live
   Claude transcript for it under ~/.claude/projects; a tracked file modified inside
   --idle-minutes. The first was once limited to process CWD, which saw 4 of 53 trees.

Report only by default. --apply is a second, deliberate run.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Generated, never work. Their presence must not make a clean tree look dirty, and their
# absence is one `setup_worktree.sh` away.
DISPOSABLE = {".venv", "node_modules", "__pycache__", ".next", "graphify-out"}
# Never snapshot these, whatever .gitignore says. .gitignore is a request; this is the rule.
EXCLUDE = [":(exclude).env", ":(exclude).env.local", ":(exclude).env.production",
           ":(exclude).lux", ":(exclude)deploy/secrets.env",
           ":(exclude)store", ":(exclude)storage", ":(exclude)node_modules", ":(exclude).venv"]



# A checker that prints failures and exits 0 is lying to whatever reads its log -- a wrapper, a
# launchd job, a founder's `&&`. Trap reported 2026-08-20 by wt-storeroot-42, who watched a gate
# print "80 FAILING CELLS" and exit 0, after which every downstream log repeated exit=0. Both
# scripts here had it: a whole object store's push could fail, or origin could decline to confirm
# the archive, and main() still returned 0. Every failure path now goes through fail().
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


def git(args: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "--no-optional-locks", *args], cwd=str(cwd),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, f"{type(e).__name__}: {e}"


def owning_clone(wt: Path) -> Path | None:
    """The clone whose .git/worktrees/<name> this tree points back at -- see defect 1."""
    dotgit = wt / ".git"
    try:
        if dotgit.is_file():
            line = dotgit.read_text(encoding="utf-8", errors="replace").strip()
            if line.startswith("gitdir:"):
                gd = Path(line.split(":", 1)[1].strip())
                # .../<clone>/.git/worktrees/<name>  ->  <clone>
                if "worktrees" in gd.parts:
                    i = gd.parts.index("worktrees")
                    return Path(*gd.parts[:i - 1])
        elif dotgit.is_dir():
            return wt
    except OSError:
        pass
    return None


def cwds_in_use() -> list[str]:
    """Every OPEN FILE PATH on the machine, in ONE call. On failure return ["/"], which keeps
    everything: a probe that cannot see is not a probe that saw nothing.

    This used to ask only for `-d cwd`, and that was too narrow to be a safety check.
    Measured 2026-08-20: of 53 worktrees, exactly 4 had a process whose CWD was the tree,
    while three peer sessions were demonstrably working in others -- their editors, test
    runs and python processes hold files open in a tree without ever chdir-ing into it.
    So the only thing standing between a working peer and a deleted tree was a 60-minute
    timer, which is a clock rather than a fact about who is working."""
    try:
        r = subprocess.run(["lsof", "-Fn"], capture_output=True, text=True, timeout=300)
        out = [ln[1:] for ln in r.stdout.splitlines() if ln.startswith("n/")]
        return out or ["/"]
    except (subprocess.TimeoutExpired, OSError):
        return ["/"]


HOLD_FILE = Path.home() / ".claude" / "estate-cleanup-hold"


def held_paths() -> set[str]:
    """Paths a session has explicitly asked to keep, one per line, '#' comments allowed.

    Every other keep-test is an inference from evidence -- an open file, a transcript, an
    mtime -- and each one has a window outside which a working session looks abandoned. A
    peer mid-task on a founder commission asked for two trees to be held; the only thing
    keeping them was a 60-minute timer, so a long quiet stretch would have removed them.
    This is the one test that is a statement rather than a guess, so it runs first and no
    later test can overturn it."""
    try:
        lines = HOLD_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return set()
    return {ln.split("#", 1)[0].strip().rstrip("/")
            for ln in lines if ln.split("#", 1)[0].strip()}


def live_session_trees(worktrees: list[Path], window_min: int = 240) -> dict[str, float]:
    """Worktrees that a Claude session has written to recently, keyed by path.

    A session's transcript lives at ~/.claude/projects/<slug>, where <slug> is the working
    directory with every non-alphanumeric character turned into '-'. Encoding is
    deterministic; decoding
    the slug back to a path is not, so this goes in the safe direction only. A session that
    is thinking, waiting on a 20-minute suite, or blocked on a review holds no file open and
    touches nothing -- it is invisible to lsof and to an mtime scan, and it is exactly the
    session whose tree must not disappear underneath it."""
    live: dict[str, float] = {}
    root = Path.home() / ".claude" / "projects"
    cutoff = time.time() - window_min * 60
    try:
        entries = list(root.iterdir())
    except OSError:
        return live
    by_slug = {e.name: e for e in entries if e.is_dir()}
    for wt in worktrees:
        # EVERY non-alphanumeric character becomes '-', not just the separator. Measured
        # against the three live slugs: the iCloud clone's real path contains both a space
        # ("Mobile Documents") and tildes ("com~apple~CloudDocs"), and all of them are '-'
        # in the slug. A str.replace("/", "-") reproduces the simple paths and silently
        # misses that one, which is the clone most likely to be holding a peer's work.
        d = by_slug.get(re.sub(r"[^A-Za-z0-9]", "-", str(wt)))
        if d is None:
            continue
        newest = 0.0
        try:
            for f in d.rglob("*.jsonl"):
                try:
                    newest = max(newest, f.stat().st_mtime)
                except OSError:
                    pass
        except OSError:
            newest = time.time()   # cannot tell -> treat as live
        if newest > cutoff:
            live[str(wt)] = newest
    return live


def real_dirt(wt: Path) -> list[str]:
    """Porcelain minus the disposable. Anything left is work."""
    rc, out = git(["status", "--porcelain"], wt)
    if rc:
        return ["<status failed: treat as dirty>"]
    keep = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        head = path.split("/", 1)[0]
        if head in DISPOSABLE or path.rstrip("/") in DISPOSABLE:
            continue
        keep.append(path)
    return keep


def newest_touch(wt: Path) -> float:
    """mtime of the most recently modified non-disposable file, two levels deep."""
    newest = 0.0
    try:
        for root, dirs, files in os.walk(wt):
            dirs[:] = [d for d in dirs if d not in DISPOSABLE and d != ".git"]
            if len(Path(root).relative_to(wt).parts) > 2:
                dirs[:] = []
            for f in files:
                try:
                    newest = max(newest, os.stat(Path(root) / f).st_mtime)
                except OSError:
                    pass
    except OSError:
        return time.time()      # cannot tell -> looks warm -> kept
    return newest


def snapshot_and_push(trees: list[Path], prefix: str, apply: bool) -> dict[Path, str]:
    """Commit each dirty tree's state to a snapshot commit and push it. Returns {tree: ref}
    for trees origin has CONFIRMED, by name and sha. Touches no working tree: the snapshot is
    built in a temporary index, so `git status` in that tree is unchanged afterwards."""
    confirmed: dict[Path, str] = {}
    by_store: dict[str, list[tuple[str, Path, str]]] = {}
    for wt in trees:
        owner = owning_clone(wt)
        if owner is None:
            print(f"    SKIP {wt.name}: cannot tell which clone owns it")
            continue
        rc, head = git(["rev-parse", "HEAD"], wt)
        if rc:
            print(f"    SKIP {wt.name}: no HEAD ({head.splitlines()[0] if head else '?'})")
            continue
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(wt / ".git_snapshot_index") if (wt / ".git").is_dir() \
            else str(Path(os.environ.get("TMPDIR", "/tmp")) / f"snapidx-{wt.name}")
        try:
            subprocess.run(["git", "read-tree", head], cwd=str(wt), env=env,
                           capture_output=True, text=True, timeout=300, check=True)
            # NOT check=True, and that is the fix rather than an oversight. `git add` exits
            # non-zero merely because some named path is also in .gitignore -- measured on
            # wt-method, where it printed "The following paths are ignored" for .env/.lux/.venv
            # and STILL wrote a correct index (write-tree gave 1d82a156). Treating that exit
            # status as failure skipped 36 of 38 dirty trees, which would have deleted nothing
            # and, worse, reported "snapshot failed" for trees whose snapshot was fine.
            # The exit status is not the outcome. The TREE is, so the tree is what gets checked.
            subprocess.run(["git", "add", "-A", "--", ".", *EXCLUDE], cwd=str(wt), env=env,
                           capture_output=True, text=True, timeout=600)
            tree = subprocess.run(["git", "write-tree"], cwd=str(wt), env=env,
                                  capture_output=True, text=True, timeout=300,
                                  check=True).stdout.strip()
            # Prove the exclusions held. .gitignore is a request; this is the check that a
            # secret cannot ride a snapshot to a remote, and it reads the object we are about
            # to push rather than the config we hoped would stop it.
            # Ask what this snapshot ADDS over HEAD, not what the tree contains. store/ and
            # storage/ are TRACKED runtime state here and .lux is partly tracked, so they are
            # in every tree derived from HEAD. A containment test therefore flagged all 33
            # dirty trees and would have snapshotted none of them -- a check so strict it
            # protects nothing, because it never lets the thing it guards happen at all.
            # What must never occur is a snapshot CARRYING a secret the commit did not
            # already have, and that is exactly a diff against HEAD.
            added = subprocess.run(["git", "diff", "--name-only", head, tree],
                                   cwd=str(wt), env=env, capture_output=True, text=True,
                                   timeout=600, check=True).stdout.splitlines()
            # PLAIN PATHS, not patterns. An earlier revision wrote "\.env" here, carrying
            # regex habits into a string comparison: python read it as the invalid escape
            # "\." and warned, and the entry matched nothing -- so the one check standing
            # between a secret and a remote was inert while reading as present.
            secret_paths = (".env", ".env.local", ".env.production", ".lux",
                            "deploy/secrets.env", "store", "storage", "node_modules", ".venv")
            leaked = sorted({e for e in secret_paths for path in added
                             if path == e or path.startswith(e + "/")})
            if leaked:
                fail(f"    SKIP {wt.name}: excluded paths reached the tree: {leaked}")
                continue
            sha = subprocess.run(["git", "commit-tree", tree, "-p", head, "-m",
                                  f"snapshot of {wt} taken by estate_cleanup"],
                                 cwd=str(wt), env=env, capture_output=True, text=True,
                                 timeout=300, check=True).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            detail = getattr(e, "stderr", "") or ""
            fail(f"    SKIP {wt.name}: snapshot failed ({type(e).__name__}) "
                 f"{detail.strip().splitlines()[-1] if detail.strip() else ''}")
            continue
        finally:
            try:
                os.unlink(env["GIT_INDEX_FILE"])
            except OSError:
                pass
        ref = f"refs/heads/{prefix}/{wt.name}-{sha[:8]}"
        by_store.setdefault(str(owner), []).append((f"{sha}:{ref}", wt, ref))

    for store, items in sorted(by_store.items()):
        specs = [s for s, _, _ in items]
        if not apply:
            print(f"    would push {len(specs)} snapshot(s) from {store}")
            continue
        rc, out = git(["push", "origin", *specs], Path(store), timeout=1800)
        if rc:
            fail(f"    PUSH FAILED for {len(specs)} snapshot(s) from {store}: {out.splitlines()[-1] if out else '?'}")
            continue
        # Defect 2's lesson, generalised: ask the SERVER, do not believe the exit status.
        rc, ls = git(["ls-remote", "origin", *[r for _, _, r in items]], Path(store), timeout=600)
        have = {ln.split("\t")[1]: ln.split("\t")[0] for ln in ls.splitlines() if "\t" in ln}
        for spec, wt, ref in items:
            want = spec.split(":", 1)[0]
            if have.get(ref) == want:
                confirmed[wt] = ref
            else:
                fail(f"    NOT CONFIRMED on origin: {ref} -- keeping {wt.name}")
    return confirmed


def rescue_ref(wt: Path, owner: Path, prefix: str, apply: bool) -> str | None:
    """Give this worktree's HEAD a branch BEFORE the worktree is removed.

    `git worktree remove` deletes the admin directory, and for a DETACHED head that
    directory holds the only ref to those commits. Remove it and they are unreachable;
    the next gc deletes them for good, and there is no undo.

    The trap is in the word "clean". `real_dirt` reports uncommitted CHANGES. It says
    nothing about unpushed COMMITS, so a tree holding a day of committed work on a
    detached head is graded clean and removed here without a trace. Measured 2026-08-20:
    that is how wt-storeroot's two commits became unreachable, and `git worktree list`
    showed several more trees on detached heads at the same moment.

    Returns the ref that holds HEAD, or None when it could not be made safe. None means
    DO NOT REMOVE: refusing to delete costs a stale directory, and the other way round
    costs work nobody can get back.
    """
    rc, head = git(["rev-parse", "HEAD"], wt)
    if rc or not head.strip():
        return None
    sha = head.strip()
    # Already on a branch, or already merged into one? Then removal loses nothing and a
    # rescue ref would be litter. refs/heads and refs/remotes only: a worktree's own
    # detached HEAD is not among them, which is exactly the case being guarded.
    rc, refs = git(["for-each-ref", "--count=1", "--contains", sha,
                    "--format=%(refname)", "refs/heads", "refs/remotes"], owner)
    if rc == 0 and refs.strip():
        return refs.strip().splitlines()[0]
    ref = f"{prefix}/{wt.name}-{sha[:8]}"
    if not apply:
        return f"would create refs/heads/{ref}"
    rc, out = git(["branch", "--force", ref, sha], owner)
    if rc:
        fail(f"    RESCUE FAILED {wt.name}: {out.splitlines()[-1] if out else '?'}")
        return None
    # Ask git what the ref points at rather than believing the exit status, the same
    # lesson the snapshot push above already paid for.
    rc, back = git(["rev-parse", f"refs/heads/{ref}"], owner)
    if rc or back.strip() != sha:
        fail(f"    RESCUE NOT CONFIRMED {wt.name}: {ref} does not point at {sha[:8]}")
        return None
    return f"refs/heads/{ref}"


def selftest() -> int:
    """Prove the property on a real repository: a clean worktree on a DETACHED head
    holding an unpushed commit must still be reachable after the worktree is removed.

    Run it with:  python3 ~/.claude/scripts/estate_cleanup.py --selftest
    """
    import tempfile
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="estate-cleanup-selftest-") as tmp:
        root = Path(tmp)
        origin, repo = root / "origin.git", root / "repo"
        subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
        for key, value in (("user.email", "t@t"), ("user.name", "t")):
            git(["config", key, value], repo)
        (repo / "seed.txt").write_text("seed\n")
        git(["add", "seed.txt"], repo)
        git(["commit", "-qm", "seed"], repo)
        git(["push", "-q", "origin", "HEAD:refs/heads/main"], repo)

        wt = root / "wt-detached"
        git(["worktree", "add", "--detach", str(wt), "HEAD"], repo)
        (wt / "work.txt").write_text("a day of work\n")
        git(["add", "work.txt"], wt)
        git(["commit", "-qm", "the commit nobody pushed"], wt)
        rc, head = git(["rev-parse", "HEAD"], wt)
        sha = head.strip()
        if rc or not sha:
            return _report(["could not build the fixture"])

        # The tree is CLEAN by this script's own definition, which is the whole trap.
        dirt = real_dirt(wt)
        if dirt:
            failures.append(f"fixture is not clean: {dirt}")

        # Before the rescue, nothing in refs/heads or refs/remotes holds that commit.
        rc, refs = git(["for-each-ref", "--contains", sha, "--format=%(refname)",
                        "refs/heads", "refs/remotes"], repo)
        if refs.strip():
            failures.append(f"fixture commit was already reachable: {refs.strip()}")

        saved = rescue_ref(wt, repo, "selftest", apply=True)
        if saved is None:
            failures.append("rescue_ref refused a rescuable HEAD")
        git(["worktree", "remove", "--force", str(wt)], repo)
        git(["worktree", "prune"], repo)

        # The property. `cat-file -e` alone is not enough: an unreachable object still
        # answers yes until gc runs, so ask what REFERENCES it.
        rc, refs = git(["for-each-ref", "--contains", sha, "--format=%(refname)",
                        "refs/heads", "refs/remotes"], repo)
        if not refs.strip():
            failures.append(f"{sha[:8]} is unreachable after the worktree was removed")

        # A HEAD that cannot be read must produce None, so the caller keeps the tree.
        if rescue_ref(root / "not-a-worktree", repo, "selftest", apply=True) is not None:
            failures.append("rescue_ref returned a ref for a path with no HEAD")

        # Report mode must not write a ref.
        wt2 = root / "wt-report"
        git(["worktree", "add", "--detach", str(wt2), "HEAD"], repo)
        (wt2 / "b.txt").write_text("b\n")
        git(["add", "b.txt"], wt2)
        git(["commit", "-qm", "second"], wt2)
        before = git(["for-each-ref", "--format=%(refname)", "refs/heads"], repo)[1]
        rescue_ref(wt2, repo, "selftest", apply=False)
        after = git(["for-each-ref", "--format=%(refname)", "refs/heads"], repo)[1]
        if before != after:
            failures.append("report mode created a ref")
    return _report(failures)


def _report(failures: list[str]) -> int:
    if failures:
        for line in failures:
            print(f"FAIL {line}")
        print(f"\n{len(failures)} failure(s)")
        return 1
    print("selftest: 5/5 passed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/Users/chidionyema/Documents/code/prospector")
    ap.add_argument("--apply", action="store_true", help="actually delete; default is report only")
    ap.add_argument("--idle-minutes", type=int, default=60)
    ap.add_argument("--session-minutes", type=int, default=240,
                    help="keep a worktree whose Claude session transcript was written to "
                         "within this many minutes (default 240)")
    ap.add_argument("--prefix", default="salvage")
    ap.add_argument("--selftest", action="store_true",
                    help="prove a removed worktree cannot take its commits with it")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    repo = Path(a.repo)

    rc, out = git(["worktree", "list", "--porcelain"], repo)
    if rc:
        print("cannot list worktrees", file=sys.stderr)
        return 2
    trees = [Path(ln.split(" ", 1)[1]) for ln in out.splitlines() if ln.startswith("worktree ")]

    cwds = cwds_in_use()
    held = held_paths()
    sessions = live_session_trees(trees, a.session_minutes)
    cutoff = time.time() - a.idle_minutes * 60
    self_tree = Path.cwd().resolve()
    print(f"    probes: {len(cwds)} open paths, {len(held)} held path(s), "
          f"{len(sessions)} tree(s) with a session active in the last {a.session_minutes} min")

    keep: list[tuple[Path, str]] = []
    dirty: list[Path] = []
    ready: list[Path] = []
    for wt in trees:
        # First, and unconditional: a request beats every inference below it.
        if str(wt).rstrip("/") in held or wt.name in held:
            keep.append((wt, f"HELD by {HOLD_FILE.name}"))
            continue
        if wt.resolve() == repo.resolve():
            keep.append((wt, "the main checkout"))
            continue
        if not wt.exists():
            keep.append((wt, "gone from disk -- prune, not remove"))
            continue
        if self_tree == wt.resolve() or str(self_tree).startswith(str(wt) + os.sep):
            keep.append((wt, "this process is inside it"))
            continue
        if any(c == str(wt) or c.startswith(str(wt) + os.sep) for c in cwds):
            keep.append((wt, "a process has a file open in it"))
            continue
        # Checked BEFORE the mtime window, because it is the case the window gets wrong: a
        # session waiting on a suite writes nothing to its tree for the whole run.
        if str(wt) in sessions:
            age = int((time.time() - sessions[str(wt)]) / 60)
            keep.append((wt, f"a Claude session wrote here {age} min ago"))
            continue
        lockdir = owning_clone(wt)
        if lockdir and (lockdir / ".git" / "worktrees" / wt.name / "index.lock").exists():
            keep.append((wt, "index.lock -- a git command is running in it"))
            continue
        if newest_touch(wt) > cutoff:
            keep.append((wt, f"touched in the last {a.idle_minutes} min"))
            continue
        d = real_dirt(wt)
        (dirty if d else ready).append(wt)

    print(f"=== {len(trees)} worktrees: {len(keep)} kept, {len(dirty)} dirty, {len(ready)} clean ===\n")
    for wt, why in keep:
        print(f"KEEP   {wt.name:<32} {why}")

    print(f"\n=== snapshotting {len(dirty)} dirty tree(s) before anything is deleted ===")
    confirmed = snapshot_and_push(dirty, a.prefix, a.apply) if dirty else {}
    for wt in dirty:
        if wt in confirmed:
            print(f"SAVED  {wt.name:<32} {confirmed[wt]}")
        else:
            print(f"KEEP   {wt.name:<32} dirty and origin has not confirmed a snapshot")

    removable = ready + [wt for wt in dirty if wt in confirmed]
    print(f"\n=== {len(removable)} worktree(s) removable ===")
    gone = 0
    for wt in removable:
        owner = owning_clone(wt)
        if owner is None:
            print(f"KEEP   {wt.name:<32} cannot tell which clone owns it")
            continue
        saved = rescue_ref(wt, owner, a.prefix, a.apply)
        if saved is None:
            fail(f"KEEP   {wt.name:<32} HEAD has no ref and none could be made "
                 f"-- refusing to remove")
            continue
        if not a.apply:
            print(f"WOULD  {wt.name:<32} via {owner} (HEAD held by {saved})")
            continue
        print(f"HELD   {wt.name:<32} HEAD -> {saved}")
        rc, out = git(["worktree", "remove", "--force", str(wt)], owner)
        if rc:
            fail(f"KEEP   {wt.name:<32} git refused: {out.splitlines()[-1] if out else '?'}")
        else:
            print(f"GONE   {wt.name:<32} (owner {owner.name})")
            gone += 1
    if a.apply:
        for clone in {str(owning_clone(w)) for w in trees if owning_clone(w)}:
            git(["worktree", "prune"], Path(clone))
    print(f"\nremoved {gone}" if a.apply else "\nReport only. Re-run with --apply.")
    return exit_status()


if __name__ == "__main__":
    sys.exit(main())
