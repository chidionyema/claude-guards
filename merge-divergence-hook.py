#!/usr/bin/env python3
"""PreToolUse(Bash) hook: refuse a `git merge <target>` when the target has
diverged wildly from HEAD, before it runs.

Real incident, 2026-08-27: merged a one-file fix branch into `fork/main`
without checking distance first -- turned out to be 1201 commits / 5011
files ahead, and the working tree was blown apart before the mistake was
caught (recovered cleanly with `git checkout . && git clean -fd`, but the
whole class is what this closes). See merge-target-divergence-guard.py for
the actual check and its own selftest.

Exit 2 blocks the tool call (Claude Code's block code, per hook-run.py's own
contract). Anything else (not a `git merge` command, no divergence, the
check itself failing to run) passes through silently -- a guard that blocks
correct work is an outage (LAW 38), so this only ever fires on a real,
measured divergence.
"""
import json
import os
import re
import subprocess
import sys

GUARD = os.path.join(os.path.dirname(__file__), "merge-target-divergence-guard.py")

# `git merge <target>` or `git merge --no-edit <target>` etc -- the target is the
# first non-flag argument after `merge`.
_MERGE_RE = re.compile(r"\bgit\s+merge\s+((?:--\S+\s+)*)(\S+)")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    cwd = str(payload.get("cwd") or os.getcwd())
    # A command that starts with `cd <dir> &&` merges inside <dir>, not in the session cwd
    # (2026-08-27: a worktree merge was refused as "unrelated histories" because the check ran
    # in ~/dev/code, where origin/main is a different repository entirely).
    cd_m = re.match(r"\s*(?:\w+=\S+\s+)*cd\s+(\S+)\s*&&", cmd)
    if cd_m:
        cwd = os.path.expanduser(os.path.expandvars(cd_m.group(1).strip("'\"")))

    m = _MERGE_RE.search(cmd)
    if not m:
        return 0
    target = m.group(2)
    if target.startswith("-") or target in ("--abort", "--continue"):
        return 0

    try:
        proc = subprocess.run(
            [sys.executable, GUARD, target], cwd=cwd,
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return 0  # the check itself failing must never block real work (LAW 38)

    if proc.returncode == 1:
        sys.stderr.write(proc.stdout + "\n")
        sys.stderr.write(
            "BLOCKED by merge-divergence-hook: this merge target has diverged "
            "far more than a sibling branch should. Check with crew / the repo "
            "owner before merging into it (2026-08-27 incident: fork/main, "
            "1201 commits / 5011 files).\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
