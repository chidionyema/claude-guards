#!/usr/bin/env python3
"""Find launchd jobs whose loaded definition points at a path that is gone.

Why this exists. launchctl runs the definition it loaded at bootstrap, not the
plist sitting on disk. A `git mv` of a script leaves a job whose plist is
correct and whose behaviour is broken, and `launchctl list` reports the LAST
exit code, so a job whose program no longer exists shows 0 with empty stderr
and reads as healthy forever.

Measured 2026-08-22 on this machine: com.estate.costsentinel and
com.estate.downshift had both been on a stale loaded definition since 13:07.
downshift, the spend brake, reported exit 0 and had not run once. Against a
measured $6,048 in seven days versus a $120/day cap, the money brake was off
and every instrument said it was on.

Read-only. Prints what it finds and exits 1 when anything is stale, so it can
gate a move or run on a schedule. The fix it prints is the whole fix.
"""
import re
import subprocess
import sys

UID = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
# Any absolute path with a script extension. An earlier cut allowlisted
# /Users, /opt and /usr/local, and a deliberately broken test job under
# /tmp walked straight past it. A guard that can only see where it was
# told to look is a guard that reports clean.
PATH_RE = re.compile(r"/[^\s\"',]+\.(?:py|sh|rb|js|pl)\b")


def loaded_labels():
    """Every loaded job label that is not Apple's own."""
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    labels = []
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        label = parts[2].strip()
        if label and not label.startswith("com.apple"):
            labels.append(label)
    return labels


def loaded_paths(label):
    """Script paths inside the definition launchd actually holds in memory."""
    try:
        out = subprocess.run(
            ["launchctl", "print", f"gui/{UID}/{label}"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except subprocess.TimeoutExpired:
        return None
    return sorted(set(PATH_RE.findall(out)))


def main():
    stale = []
    unreadable = []
    checked = 0
    for label in loaded_labels():
        paths = loaded_paths(label)
        if paths is None:
            unreadable.append(label)
            continue
        checked += 1
        import os
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            stale.append((label, missing))

    print(f"checked {checked} loaded jobs")
    if unreadable:
        print(f"could not read {len(unreadable)}: {', '.join(unreadable)}")

    if not stale:
        print("no drift: every loaded definition points at a path that exists")
        return 0

    print(f"\nSTALE: {len(stale)} job(s) run a definition naming a path that is gone.")
    print("launchctl list will still report the old exit code for these.\n")
    for label, missing in stale:
        print(f"  {label}")
        for p in missing:
            print(f"      MISSING {p}")
        print(f"      fix: launchctl bootout gui/{UID}/{label} && "
              f"launchctl bootstrap gui/{UID} ~/Library/LaunchAgents/{label}.plist")
    return 1


if __name__ == "__main__":
    sys.exit(main())
