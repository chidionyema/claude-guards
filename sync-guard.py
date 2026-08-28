#!/usr/bin/env python3
"""The Mac runs main. At every SessionStart the live guards checkout fast-forwards to origin/main,
or says exactly which file stops it (crew#603 CP2).

WHY THIS EXISTS. Founder, 2026-08-28: "Force Auto-Sync. The Mac must pull the latest code from
main on every single session start." Measured 2026-08-28 22:4xZ: ~/.claude/scripts sat at
0ef86d5, 33 commits behind origin/main, so the fail-closed door merged in cg#207 (37fa8f0) was
enforcing nothing on the machine it was written for. Three locally edited files
(auto-objective.py, policy/command.rego, rulings.json) belonged to other sessions and would have
collided with the fast-forward.

WHAT IT DOES. fetch; if HEAD is already origin/main, one line. If a fast-forward applies with
no locally modified file in its path, apply it and say what moved. Otherwise say BLOCKED with
the branch, the count and every colliding file, so the owner commits or discards it. It never
resets, stashes or checks out over a person's edit (LAW 11), and it never blocks the session
itself: a session that cannot start cannot fix the checkout. Exit is always 0; what fails closed
is the door (hook-run.py), not the hand that keeps the door current.

Reads: git only. Writes: the fast-forward, nothing else. Network: one fetch, 20 s cap.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

SCRIPTS = pathlib.Path(os.environ.get("SYNC_GUARD_DIR") or pathlib.Path(__file__).resolve().parent)
REMOTE = os.environ.get("SYNC_GUARD_REMOTE", "origin")
BRANCH = os.environ.get("SYNC_GUARD_BRANCH", "main")
TAG = "[sync]"


def git(*args: str, timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(SCRIPTS), *args], text=True, capture_output=True, timeout=timeout)


def out(*args: str) -> str:
    return git(*args).stdout.strip()


def main() -> int:
    target = f"{REMOTE}/{BRANCH}"
    try:
        fetched = git("fetch", "--quiet", REMOTE, BRANCH)
    except subprocess.TimeoutExpired:
        print(f"{TAG} BLIND: fetch of {target} timed out; {SCRIPTS} may be stale")
        return 0
    if fetched.returncode != 0:
        print(f"{TAG} BLIND: fetch failed ({fetched.stderr.strip().splitlines()[-1] if fetched.stderr.strip() else 'no reason'}); {SCRIPTS} may be stale")
        return 0
    head = out("rev-parse", "--short", "HEAD")
    remote_sha = out("rev-parse", "--short", target)
    behind = int(out("rev-list", "--count", f"HEAD..{target}") or 0)
    ahead = int(out("rev-list", "--count", f"{target}..HEAD") or 0)
    branch = out("rev-parse", "--abbrev-ref", "HEAD")
    if behind == 0 and ahead == 0:
        print(f"{TAG} ok {SCRIPTS} is {target} at {head}")
        return 0
    detached = branch == "HEAD"  # ~/.claude/scripts is a submodule of ~/.claude: detached is its normal state
    if ahead or (branch != BRANCH and not detached):
        why = f"on branch {branch}" if not ahead else f"ahead of {target} by {ahead} unpushed commit(s)"
        print(f"{TAG} BLOCKED: {SCRIPTS} is {why} and {behind} behind {target} ({remote_sha}); "
              f"a fast-forward cannot apply. Push or move the commits, then start a session.")
        return 0
    incoming = set(out("diff", "--name-only", f"HEAD...{target}").splitlines())
    # not out(): porcelain rows start with a status column that may be a space, and strip() eats it
    dirty = {line[3:].split(" -> ")[-1] for line in git("status", "--porcelain", "--untracked-files=all").stdout.splitlines() if len(line) > 3}
    collide = []
    for path in sorted(incoming & dirty):
        # A local copy that already equals the target blob is a session that edited what main then
        # merged, not a collision: align the index so the fast-forward can walk over it unchanged.
        target_blob = git("show", f"{target}:{path}")
        local = SCRIPTS / path
        if target_blob.returncode == 0 and local.is_file() and local.read_text(errors="replace") == target_blob.stdout:
            git("checkout", "--quiet", target, "--", path)
        else:
            collide.append(path)
    if collide:
        print(f"{TAG} BLOCKED: {SCRIPTS} is {behind} behind {target} ({remote_sha}) and these locally "
              f"edited files are in the fast-forward's path: {', '.join(collide)}. Their owner commits or "
              f"discards them (git -C {SCRIPTS} checkout -- <file>); nothing was reset.")
        return 0
    merged = (git("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", target) if detached
              else git("merge", "--ff-only", "--quiet", target))
    if merged.returncode != 0:
        print(f"{TAG} BLOCKED: fast-forward to {target} refused: {merged.stderr.strip().splitlines()[-1] if merged.stderr.strip() else merged.returncode}")
        return 0
    print(f"{TAG} synced {SCRIPTS} {head} -> {remote_sha} ({behind} commit(s) from {target})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never stop a session from starting; say what broke
        print(f"{TAG} BLIND: {type(exc).__name__}: {exc}")
        sys.exit(0)
