#!/usr/bin/env python3
"""Refuse a skill that hard-codes a path only one machine has.

The deputy's CI job runs the skills on Linux for one reason: to refuse a broken
skill before it reaches the Mac. A skill that hard-codes "/System/Volumes/Data"
or a home directory under /Users cannot run on the runner at all, so the job
stops being a check and becomes a crash. disk_cleanup.py did exactly that, and
the deputy job was red on main from 2026-08-23 to 2026-08-24 with nobody reading it.

Derive the path from HOME, or take it from the caller.

This reads string values out of the parsed syntax tree, not lines of text. A
grep over source would flag this very docstring, and a guard that refuses
correct work is an outage. Comments never reach the tree; docstrings are
skipped by name.

    _no_machine_paths.py            check skills/, exit 1 on a hit
    _no_machine_paths.py --selftest prove it refuses one and permits the tree
"""

import ast
import re
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SELF = pathlib.Path(__file__).name

# Roots that exist on one operating system, or on one person's laptop. "/tmp"
# and "/dev/null" are on every machine the deputy will ever run on and stay legal.
MACHINE_PATH = re.compile(r"^/(System/Volumes|Users|Library|private/var)(/|$)")

_HAS_DOC = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def offenders_in_source(name: str, src: str):
    """String values in `src` that name a machine-specific absolute path.

    A file that will not parse is reported, never skipped: a guard with a silent
    miss case reports PASS on the one file it could not read.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"{name}:{exc.lineno}: does not parse, so it was not checked: {exc.msg}"]

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, _HAS_DOC) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(id(first.value))

    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings and MACHINE_PATH.match(node.value):
            hits.append(f"{name}:{node.lineno}: {node.value!r}")
    return hits


def offenders(directory: pathlib.Path):
    hits = []
    for path in sorted(directory.glob("*.py")):
        if path.name == SELF:
            continue
        hits.extend(offenders_in_source(path.name, path.read_text()))
    return hits


def selftest() -> int:
    must_refuse = {
        "the line that broke the deputy": 'import os\nst = os.statvfs("/System/Volumes/Data")\n',
        "a home directory literal": "LOG = '/Users/chidionyema/.claude/x.log'\n",
        "a launch agent path": 'P = "/Library/LaunchAgents/com.x.plist"\n',
        "a file that will not parse": "def broken(:\n",
    }
    must_permit = {
        "a portable device": 'open("/dev/null")\n',
        "a portable temp path": 'TMP = "/tmp/x"\n',
        "a path built from HOME": 'import os\nos.path.join(HOME, "Library", "Caches")\n',
        "the path named in prose": '"""Not a hard-coded /Users/me/x, see below."""\n',
        "a relative path": 'P = "skills/disk_cleanup.py"\n',
    }
    fails = []
    for label, src in must_refuse.items():
        if not offenders_in_source("case", src):
            fails.append(f"  MISSED (should refuse): {label}")
    for label, src in must_permit.items():
        got = offenders_in_source("case", src)
        if got:
            fails.append(f"  FALSE POSITIVE (should permit): {label} -> {got}")
    live = offenders(HERE)
    for h in live:
        fails.append(f"  LIVE OFFENDER: {h}")
    for line in fails:
        print(line)
    ok = not fails
    print(f"  selftest {'PASS' if ok else 'FAIL'}: {len(must_refuse)} refused, "
          f"{len(must_permit)} permitted, {len(live)} live offenders")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    hits = offenders(HERE)
    if hits:
        print("::error::a skill hard-codes a machine-specific absolute path; derive it from HOME")
        print("\n".join(f"  {h}" for h in hits))
        return 1
    print("  no machine-specific absolute paths in skills/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
