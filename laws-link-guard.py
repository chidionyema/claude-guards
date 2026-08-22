#!/usr/bin/env python3
"""Keep every provider's rules file pointing at ~/AGENTS.md.

The laws are one file. Each agent tool reads them through a symlink in its own
directory. An editor that saves by writing a temp file and renaming it over the
target replaces the symlink with a regular copy, and from then on the two drift
apart in silence. ~/.claude holds fourteen CLAUDE.md.bak-* files, so wholesale
rewrites of this file are routine here, not hypothetical.

This restores the links. If a provider path has become a regular file that
differs from ~/AGENTS.md, the newer text wins and the older is kept beside it
rather than thrown away, because a fork usually means somebody edited the wrong
copy and that edit is real work.

Run it any time; it is idempotent and prints only when it changed something.
"""
import os
import shutil
import sys
import time

HOME = os.path.expanduser("~")
CANON = os.path.join(HOME, "AGENTS.md")
# The laws stopped being version controlled the moment the real file moved out
# of the ~/.claude repo. This keeps a tracked snapshot inside it - backups/ is
# gitignored, so it had to sit at the repo root - which gives git its history
# back and gives a deleted ~/AGENTS.md something to come back from.
SNAPSHOT = os.path.join(HOME, ".claude", "AGENTS.snapshot.md")

# Deliberately NOT ~/CLAUDE.md. A session whose working directory is $HOME
# reads that as a project memory file, so the laws would be injected a second
# time and billed a second time. Claude Code enters through ~/.claude/CLAUDE.md,
# which imports AGENTS.md.
LINKS = [
    os.path.join(HOME, ".claude", "AGENTS.md"),
    os.path.join(HOME, ".codex", "AGENTS.md"),
    os.path.join(HOME, ".gemini", "GEMINI.md"),
    os.path.join(HOME, ".cursor", "AGENTS.md"),
]


def rel_target(link: str) -> str:
    return os.path.relpath(CANON, os.path.dirname(link))


def main() -> int:
    changed = []

    if not os.path.exists(CANON):
        # The one copy is gone. Come back from the newest thing that survives:
        # a provider copy that was never a symlink, or the snapshot.
        cands = [p for p in LINKS if os.path.isfile(p) and not os.path.islink(p)]
        if os.path.isfile(SNAPSHOT):
            cands.append(SNAPSHOT)
        if not cands:
            print("laws-link-guard: ~/AGENTS.md is missing and no copy survives", file=sys.stderr)
            return 1
        newest = max(cands, key=os.path.getmtime)
        shutil.copy2(newest, CANON)
        changed.append(f"restored ~/AGENTS.md from {newest}")

    for link in LINKS:
        if not os.path.isdir(os.path.dirname(link)):
            continue  # that tool is not installed on this machine
        if os.path.islink(link) and os.path.realpath(link) == os.path.realpath(CANON):
            continue
        if os.path.isfile(link) and not os.path.islink(link):
            with open(link, "rb") as a, open(CANON, "rb") as b:
                same = a.read() == b.read()
            if not same:
                if os.path.getmtime(link) > os.path.getmtime(CANON):
                    shutil.copy2(CANON, CANON + ".forked-" + time.strftime("%Y-%m-%d-%H%M%S"))
                    shutil.copy2(link, CANON)
                    changed.append(f"{link} was newer and different: promoted to ~/AGENTS.md")
                else:
                    keep = link + ".forked-" + time.strftime("%Y-%m-%d-%H%M%S")
                    shutil.copy2(link, keep)
                    changed.append(f"{link} had drifted and was older: kept at {keep}")
            os.remove(link)
        elif os.path.lexists(link):
            os.remove(link)
        os.symlink(rel_target(link), link)
        changed.append(f"relinked {link} -> {rel_target(link)}")

    # Snapshot last, so it records the state the links now agree on.
    if os.path.isfile(CANON):
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        stale = True
        if os.path.isfile(SNAPSHOT):
            with open(SNAPSHOT, "rb") as a, open(CANON, "rb") as b:
                stale = a.read() != b.read()
        if stale:
            shutil.copy2(CANON, SNAPSHOT)
            changed.append(f"snapshot updated: {SNAPSHOT}")

    for line in changed:
        print("laws-link-guard:", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
