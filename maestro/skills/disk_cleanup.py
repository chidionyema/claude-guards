#!/usr/bin/env python3
"""Reclaim disk without losing anything that cannot be regenerated.

Only touches caches and build droppings. Everything it deletes is rebuilt by the
next run of the tool that made it, which is what makes this skill reversible and
therefore eligible for the auto-fix lane. It never touches source, git objects,
databases, logs it did not write, or anything outside HOME.

    disk_cleanup.py --json        do it, print evidence
    disk_cleanup.py --dry-run     print what it would reclaim, change nothing
"""

import os
import sys
import json
import shutil
import subprocess

HOME = os.path.expanduser("~")

# Regenerable by definition. Anything not on this list is out of scope for the skill.
CACHE_DIRS = ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")
ROOTS = (
    os.path.join(HOME, ".claude"),
    os.path.join(HOME, "dev", "code"),
    os.path.join(HOME, "Documents", "code"),
)
SKIP = (".git", "node_modules", ".venv", "venv", "Library")


def _size(path: str) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: None):
        for f in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def find_caches():
    hits = []
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, _ in os.walk(root, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            for d in list(dirnames):
                if d in CACHE_DIRS:
                    p = os.path.join(dirpath, d)
                    hits.append((p, _size(p)))
                    dirnames.remove(d)
    return hits


def prune_worktrees():
    """Stale worktree registrations point at directories that no longer exist."""
    pruned = []
    for repo in (os.path.join(HOME, "Documents", "code", "prospector"),
                 os.path.join(HOME, "dev", "code", "crew")):
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        r = subprocess.run(["git", "-C", repo, "worktree", "prune", "-v"],
                           capture_output=True, text=True, timeout=120)
        if r.stdout.strip():
            pruned.append({"repo": repo, "output": r.stdout.strip()[:800]})
    return pruned


def free_bytes() -> int:
    """Free bytes on the volume HOME sits on.

    Not a hard-coded "/System/Volumes/Data". That path exists only on macOS, so
    the deputy's CI job crashed here on every run: the job runs on Linux, and it
    exists to refuse a broken skill before it reaches the Mac. It was red from
    2026-08-23 to 2026-08-24 for this one line.

    On the Mac this reads the same volume it always did. Measured 2026-08-24:
    statvfs(HOME) and statvfs("/System/Volumes/Data") both returned
    132848467968 free bytes.
    """
    st = os.statvfs(HOME)
    return st.f_bavail * st.f_frsize


def main() -> int:
    dry = "--dry-run" in sys.argv
    before = free_bytes()
    caches = find_caches()
    reclaimable = sum(s for _, s in caches)

    removed, failed = [], []
    if not dry:
        for path, size in caches:
            try:
                shutil.rmtree(path)
                removed.append({"path": path, "bytes": size})
            except OSError as exc:
                failed.append({"path": path, "error": str(exc)})

    evidence = {
        "skill": "disk_cleanup",
        "dry_run": dry,
        "cache_dirs_found": len(caches),
        "reclaimable_mb": round(reclaimable / 1e6, 1),
        "removed": len(removed),
        "failed": len(failed),
        "worktrees_pruned": [] if dry else prune_worktrees(),
        "free_mb_before": round(before / 1e6, 1),
        "free_mb_after": round(free_bytes() / 1e6, 1),
    }
    print(json.dumps(evidence, indent=2))
    # Failing to delete one cache is not a failed skill; finding nothing to do is a success.
    return 1 if failed and not removed else 0


if __name__ == "__main__":
    sys.exit(main())
