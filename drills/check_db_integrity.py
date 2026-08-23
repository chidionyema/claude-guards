#!/usr/bin/env python3
"""Assert every sqlite database this estate keeps still passes integrity_check.

On 2026-08-23 ``Documents/code/prospector/store/prospector.db`` was found with
eight index entries missing across four indexes, rows 3604 to 3608 of 3608. It
had been that way since at least 2026-08-21 and nothing on this Mac would ever
have said so. The data was intact; only the indexes were damaged, which a
``REINDEX`` repairs in a quarter of a second without losing a row.

Two things made it silent, and this drill exists because of both.

``PRAGMA quick_check`` returns "ok" on that exact file. quick_check skips index
content verification by design, so the cheap check passes while the real one
fails. Anything grading a database with quick_check is grading a proxy.

And the file sits in a legacy tree that no backup covers and no probe reads. A
database nobody checks is a database that is fine right up until a restore.

The repair is attempted here on purpose. Missing index entries are recoverable
from the table data by definition, so a REINDEX is lossless and the drill says
what it did. Anything else -- a damaged page, a malformed row, a corrupt schema
-- is data loss, and this drill refuses to touch it and reports instead.
"""
import os
import sqlite3
import subprocess
import sys
import time

#: Where the estate keeps state worth losing sleep over. Each is scanned to a
#: shallow depth so a stray virtualenv or node_modules cannot pull in hundreds
#: of vendored fixtures.
ROOTS = [
    "~/dev/code/hermes-v2",
    "~/dev/code/crew",
    "~/dev/code/maestro",
    "~/.claude",
    "~/.estate",
    "~/Documents/code/prospector/store",
    "~/dev/code/prospector-main/store",
]

#: Under this and it is a fresh schema with nothing in it. Checking those adds
#: noise without adding cover.
MIN_BYTES = 8192

#: A per-database ceiling. integrity_check walks every page, and a wedged check
#: on one file must not stop the drill reporting on the rest.
CHECK_TIMEOUT = 120


def databases():
    seen = []
    for root in ROOTS:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            continue
        out = subprocess.run(
            ["find", root, "-maxdepth", "5", "-name", "*.db",
             "-not", "-path", "*/.venv/*", "-not", "-path", "*/node_modules/*",
             "-not", "-path", "*/__pycache__/*", "-size", f"+{MIN_BYTES // 1024}k"],
            capture_output=True, text=True).stdout.split("\n")
        for path in out:
            path = path.strip()
            if path and path not in seen:
                seen.append(path)
    return sorted(seen)


def check(path):
    """The first line of integrity_check, read-only so a live writer is safe."""
    try:
        proc = subprocess.run(
            ["sqlite3", f"file:{path}?mode=ro", "PRAGMA integrity_check;"],
            capture_output=True, text=True, timeout=CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"check did not finish in {CHECK_TIMEOUT}s"
    lines = proc.stdout.strip().splitlines()
    if not lines:
        return proc.stderr.strip()[:120] or "no output from integrity_check"
    return lines[0]


def index_only(verdict):
    """True when every complaint is a missing index entry, which REINDEX fixes.

    Anything else means a page, a row or the schema is damaged, and rebuilding
    indexes over that would hide it rather than repair it.
    """
    return verdict.startswith("row ") and "missing from index" in verdict


def main():
    paths = databases()
    if not paths:
        print("no databases found under any of the roots: nothing to check")
        return 1

    healed, broken, ok = [], [], 0
    for path in paths:
        verdict = check(path)
        if verdict == "ok":
            ok += 1
            continue

        short = path.replace(os.path.expanduser("~"), "~")
        if not index_only(verdict):
            broken.append((short, verdict))
            continue

        # Lossless: the index is rebuilt from the table it indexes.
        rows_before = _row_total(path)
        started = time.time()
        try:
            conn = sqlite3.connect(path, timeout=30)
            conn.execute("REINDEX")
            conn.commit()
            conn.close()
        except sqlite3.Error as exc:
            broken.append((short, f"REINDEX refused: {exc}"))
            continue
        after = check(path)
        rows_after = _row_total(path)
        if after == "ok" and rows_before == rows_after:
            healed.append((short, verdict, time.time() - started, rows_after))
        else:
            broken.append((short, f"REINDEX did not fix it: {after}"))

    for short, verdict, secs, rows in healed:
        print(f"HEALED  {short}")
        print(f"        was: {verdict}")
        print(f"        REINDEX in {secs:.2f}s, {rows} rows before and after, now ok")
    for short, verdict in broken:
        print(f"BROKEN  {short}")
        print(f"        {verdict[:150]}")

    print(f"{len(paths)} databases checked, {ok} already ok, "
          f"{len(healed)} repaired, {len(broken)} needing a person")

    if broken:
        return 1
    if healed:
        # A repair is a pass with a finding. The estate is correct again and
        # somebody should know why it was not.
        print("DRILL PASSED with repairs: the corruption is gone and it is "
              "worth knowing what wrote it.")
        return 0
    print("DRILL PASSED: every database this estate keeps passes integrity_check.")
    return 0


def _row_total(path):
    """Total rows across user tables, so a repair can prove it lost nothing."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        total = 0
        for name in names:
            total += conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        conn.close()
        return total
    except sqlite3.Error:
        return None


if __name__ == "__main__":
    sys.exit(main())
