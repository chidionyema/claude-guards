#!/usr/bin/env python3
"""Find launchd jobs whose declared paths still land inside ~/Documents.

macOS TCC hides ~/Documents from a bootstrapped LaunchAgent. A job pointed there
does not fail loudly: it fails on schedule, exits, and `launchctl list` reports
the last exit code forever. com.founder.estatepush failed exactly this way and
passed by hand every time anyone checked.

This resolves symlinks before judging, which is the point. ~/.hermes is a symlink,
so the string "~/.hermes" in a plist says nothing about where the job actually
reads. If that symlink is repointed at ~/dev/code/hermes, every one of these jobs
becomes correct without a single plist changing, and a checker that greps for the
string would still be shouting. Grep the destination, not the spelling.

Sibling of launchd_drift.py, which asks the other half of the question: whether the
LOADED definition points at a path that exists at all.
"""
from __future__ import annotations

import os
import plistlib
import re
import sys
from pathlib import Path

AGENTS = Path.home() / "Library" / "LaunchAgents"
FORBIDDEN = (Path.home() / "Documents").resolve()

# Any absolute path, wherever it appears. An earlier guard in this directory
# allowlisted three prefixes and walked straight past a broken job under /tmp.
PATH_RE = re.compile(r"/[^\s\"',<>]+")


def paths_in(value) -> list[str]:
    """Every absolute-looking path anywhere in a plist value, at any depth."""
    if isinstance(value, str):
        return PATH_RE.findall(value)
    if isinstance(value, list):
        return [p for v in value for p in paths_in(v)]
    if isinstance(value, dict):
        return [p for v in value.values() for p in paths_in(v)]
    return []


def under_documents(path: str) -> str | None:
    """The resolved path, if it lands inside ~/Documents. None otherwise."""
    try:
        real = Path(os.path.realpath(os.path.expanduser(path)))
    except (OSError, ValueError):
        return None
    try:
        real.relative_to(FORBIDDEN)
    except ValueError:
        return None
    return str(real)


def main() -> int:
    if not AGENTS.is_dir():
        print(f"no {AGENTS}", file=sys.stderr)
        return 0

    plists = sorted(AGENTS.glob("*.plist"))
    offenders: dict[str, list[tuple[str, str]]] = {}
    unreadable: dict[str, str] = {}

    for pl in plists:
        try:
            data = plistlib.loads(pl.read_bytes())
        except Exception as exc:
            # Its own finding, kept apart from the Documents count. A plist that a
            # standard XML parser refuses still loads under launchd, because plutil
            # and Apple's parser are more forgiving than expat -- a comment holding
            # a double hyphen is the case that bit here. So the job runs, the file
            # lints clean, and every Python tool that opens it throws and skips the
            # job without a word. Counting that as a Documents hit would hide it.
            unreadable[pl.name] = repr(exc)
            continue
        hits = []
        for raw in dict.fromkeys(paths_in(data)):      # dedupe, keep order
            real = under_documents(raw)
            if real:
                hits.append((raw, real))
        if hits:
            offenders[pl.name] = hits

    print(f"checked {len(plists)} plists in {AGENTS}")

    if unreadable:
        print(f"\n{len(unreadable)} plist(s) a standard XML parser cannot read. "
              f"launchd loads them anyway,\nso every Python tool skips these jobs "
              f"in silence:\n")
        for name, err in unreadable.items():
            print(f"  {name}\n      {err}")

    if not offenders:
        print("\nclean: no declared path resolves inside ~/Documents")
        return 1 if unreadable else 0

    print(f"\n{len(offenders)} job(s) still resolve into ~/Documents, which TCC hides "
          f"from a bootstrapped LaunchAgent.\nThese fail on schedule and pass by hand.\n")
    for name, hits in offenders.items():
        print(f"  {name}")
        for raw, real in hits:
            print(f"      {raw}")
            print(f"        -> {real}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
