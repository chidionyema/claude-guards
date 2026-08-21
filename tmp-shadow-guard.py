#!/usr/bin/env python3
"""Quarantine any file in /tmp whose name shadows a Python standard library module.

WHY THIS EXISTS. Measured 2026-08-21. A session saved a page-fetcher to `/private/tmp/gettext.py`
at 04:14. `argparse` does `from gettext import gettext as _`, and Python puts the SCRIPT'S OWN
DIRECTORY at the front of sys.path -- so from that moment every `python3 /tmp/<anything>.py` that
used argparse imported the fetcher instead of the standard library, and the fetcher immediately
opened a network connection to whatever `sys.argv[1]` happened to be.

There were 260 .py files in /tmp at the time. The estate writes scratch scripts there constantly.

WHAT IT ACTUALLY COST. The SessionStart hook that keeps the shared developer checkout on
origin/main runs `python3 /tmp/checkout_currency.py --fix`. It died on every session start with

    ValueError: unknown url type: '--fix'

raised inside urllib, from a traceback naming argparse and gettext and nothing else. Nobody read
it as a shadowed import, so the guard stayed dead and the checkout drifted. When this was fixed
the very first run reported STALE and fast-forwarded 3 commits -- sessions had been briefed from
old rules, which is the exact recurring failure that hook was built to stop.

THE CLASS: a scratch file in a shared directory is on the import path of every script run from
that directory. The name is the whole attack surface, and a plausible name is the dangerous one.
`/tmp/os.py` had also been sitting there since 2026-08-17. That one never fired only because `os`
is already in sys.modules before any script runs -- luck, not safety.

Renames rather than deletes: the file is somebody's working tool and the content is kept.
Quarantined files land in ~/.claude/state/tmp-shadow-quarantine/ and a safe-named copy is left in
/tmp so the owner's next call still works.

  python3 ~/.claude/scripts/tmp-shadow-guard.py            # quarantine and report (SessionStart)
  python3 ~/.claude/scripts/tmp-shadow-guard.py --report   # report only, change nothing
  python3 ~/.claude/scripts/tmp-shadow-guard.py --selftest
"""
from __future__ import annotations

import pathlib
import shutil
import sys

TMPDIRS = (pathlib.Path("/private/tmp"), pathlib.Path("/tmp"))
QUARANTINE = pathlib.Path.home() / ".claude" / "state" / "tmp-shadow-quarantine"

# Not every stdlib name is worth moving somebody's file for. These are the ones a scratch script
# plausibly gets named AND that a common import chain pulls in lazily, so the shadow actually
# fires. `os`, `sys` and friends are already in sys.modules before a script runs, but they are
# included anyway: a file called os.py is a trap even when it is currently inert.
def shadowing(paths=TMPDIRS) -> list[pathlib.Path]:
    std = set(sys.stdlib_module_names)
    seen, out = set(), []
    for d in paths:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            real = f.resolve()
            if real in seen or f.stem not in std or f.stem.startswith("_"):
                continue
            seen.add(real)
            out.append(f)
    return out


def quarantine(f: pathlib.Path, stamp: str, qdir: pathlib.Path = QUARANTINE) -> pathlib.Path:
    """Move it out of the import path, and leave a safe-named copy so its owner is not broken."""
    qdir.mkdir(parents=True, exist_ok=True)
    dest = qdir / f"{f.name}.quarantined-{stamp}"
    n = 1
    while dest.exists():
        n += 1
        dest = qdir / f"{f.name}.quarantined-{stamp}.{n}"
    shutil.move(str(f), str(dest))
    safe = f.with_name(f"_{f.stem}_shadowed{f.suffix}")
    if not safe.exists():
        shutil.copy2(str(dest), str(safe))
    return dest


def selftest() -> int:
    import tempfile
    p = f = 0

    def ck(name, ok):
        nonlocal p, f
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if ok:
            p += 1
        else:
            f += 1

    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "gettext.py").write_text("x=1\n")
        (d / "os.py").write_text("x=1\n")
        (d / "notes.py").write_text("x=1\n")
        (d / "_gettext.py").write_text("x=1\n")
        (d / "gettext.txt").write_text("x=1\n")
        found = {x.name for x in shadowing([d])}
        ck("a file named after a stdlib module is found", "gettext.py" in found)
        ck("the one that actually cost us four hours is found", "os.py" in found)
        ck("an ordinary scratch name is left alone", "notes.py" not in found)
        ck("an already-safe underscore name is not re-flagged", "_gettext.py" not in found)
        ck("a non-.py file with a stdlib name is not touched", "gettext.txt" not in found)

        q = d / "q"
        dest = quarantine(d / "gettext.py", "TEST", q)
        ck("the shadow is gone from the import path", not (d / "gettext.py").exists())
        ck("the content is preserved in quarantine", dest.exists() and dest.read_text() == "x=1\n")
        ck("a safe-named copy is left so the owner's tool still runs",
           (d / "_gettext_shadowed.py").exists())
        ck("re-scanning after quarantine finds it no longer shadows",
           "gettext.py" not in {x.name for x in shadowing([d])})

        # A second file with the same name must not overwrite the first quarantined copy.
        (d / "gettext.py").write_text("y=2\n")
        dest2 = quarantine(d / "gettext.py", "TEST", q)
        ck("a second quarantine of the same name does not clobber the first",
           dest2 != dest and dest.read_text() == "x=1\n" and dest2.read_text() == "y=2\n")

    print(f"\n  {p}/{p + f} checks passed")
    return 0 if f == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    report_only = "--report" in sys.argv
    hits = shadowing()
    if not hits:
        return 0
    print("[tmp-shadow-guard] a file in /tmp shadows a Python standard library module.")
    print("  Every `python3 /tmp/<script>.py` that imports it gets THIS file instead of the")
    print("  standard library, and the traceback will name anything but the real cause.")
    for f in hits:
        if report_only:
            print(f"  SHADOWS '{f.stem}': {f}")
            continue
        dest = quarantine(f, "auto")
        print(f"  SHADOWS '{f.stem}': {f}")
        print(f"    -> moved to {dest}")
        print(f"    -> safe copy left at {f.with_name('_' + f.stem + '_shadowed.py')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
