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


def uninvert() -> str:
    """Put the laws back at CANON if somebody made CANON the symlink.

    An agent following LAW 24 reasonably concludes the laws should live inside
    the tracked repository, moves ~/AGENTS.md to ~/.claude/AGENTS.md and points
    ~/AGENTS.md at it. That reads fine and is fatal here: the loop below then
    replaces ~/.claude/AGENTS.md with a link to ../AGENTS.md, which is now a
    link back, and 64,920 bytes of laws become a symlink cycle that resolves to
    nothing. It happened on 2026-08-23 and was caught before the hook ran.

    The laws are already in git as AGENTS.snapshot.md, so the inversion buys
    nothing. Undo it rather than refuse, because a Stop hook that blocks gets
    switched off.
    """
    if not os.path.islink(CANON):
        return ""
    real = os.path.realpath(CANON)
    #: realpath() of a symlink is the file it lands on, and realpath() of that
    #: file is itself, so comparing the two always says "equal". An earlier
    #: version guarded on exactly that and never fired once.
    if not os.path.isfile(real) or os.path.islink(real):
        return ""
    #: Match back to the literal LINKS path, not the realpath. On macOS /var is
    #: itself a symlink to /private/var, and relinking against the resolved form
    #: writes a nine-hop relative path that works but reads as damage.
    link = next((l for l in LINKS
                 if os.path.realpath(os.path.dirname(l)) == os.path.realpath(os.path.dirname(real))
                 and os.path.basename(l) == os.path.basename(real)), "")
    if not link:
        return ""                       # pointed somewhere else on purpose
    body = open(real, "rb").read()
    os.remove(CANON)
    with open(CANON, "wb") as f:
        f.write(body)
    os.remove(link)
    os.symlink(rel_target(link), link)
    return f"topology was inverted: the laws are a file at {CANON} again, {link} links to it"


def main() -> int:
    changed = []

    flip = uninvert()
    if flip:
        changed.append(flip)

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
