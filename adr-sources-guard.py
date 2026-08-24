#!/usr/bin/env python3
"""Refuse a decision record that cites nothing.

THE RULING THIS ENFORCES. R17, founder, 2026-08-24: "ok good job but alway research, it
pays off all the tine". Said right after research reversed a decision that was already
being built.

THE INCIDENT. A session started standing up an estate ingress configured with Traefik's own
Docker labels. It had not searched anything. Two facts it did not know, both found in one
search: Kubernetes SIG Network retired the ingress-nginx controller on 2026-03-24, and
Gateway API core is GA at v1.6.0 with sixteen conformant implementations. The real decision
turned out to be the config language rather than the vendor -- routes written as HTTPRoute
are portable, routes written as vendor labels are not. The founder stopped it: "wrong,
research firdt", "we cnt naake it up on the spot", "we need to see industry standards".

THE CLASS, in one sentence: a decision that binds the platform is recorded without the
evidence it was based on, so nobody after can tell whether it was researched or guessed.

Not "ADRs must be long". A decision citing two dated sources passes. A decision citing none
is indistinguishable from one made from memory, and memory is what R17 forbids.

WHAT COUNTS. A '## Sources' heading, and at least two http(s) URLs anywhere in the file.
Two, because one source is a vendor's own page about itself.

    python3 ~/.claude/scripts/adr-sources-guard.py --selftest
    python3 ~/.claude/scripts/adr-sources-guard.py --sweep [root ...]     # report only
"""
from __future__ import annotations

import os
import re
import sys

URL = re.compile(r'https?://[^\s<>)\]"\']+')
HEADING = re.compile(r'^#{1,6}\s*sources\b', re.I | re.M)
MIN_URLS = 2


def failures(text: str) -> list[str]:
    """Empty list means the record is acceptable."""
    bad = []
    if not HEADING.search(text):
        bad.append("no '## Sources' heading")
    n = len(set(URL.findall(text)))
    if n < MIN_URLS:
        bad.append(f"{n} distinct source URL(s), needs {MIN_URLS}")
    return bad


def is_adr(path: str) -> bool:
    parts = path.lower().split(os.sep)
    if not path.lower().endswith(".md"):
        return False
    if "decisions" in parts or any(p.startswith("adr") for p in parts):
        return not os.path.basename(path).lower().startswith(("readme", "index", "template"))
    return False


def sweep(roots: list[str]) -> int:
    found = clean = 0
    bad: list[tuple[str, list[str]]] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in {".git", "node_modules", ".venv", "worktrees", ".claude"}]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                if not is_adr(p):
                    continue
                found += 1
                try:
                    why = failures(open(p, encoding="utf-8", errors="replace").read())
                except OSError as e:
                    why = [f"unreadable: {e}"]
                if why:
                    bad.append((p, why))
                else:
                    clean += 1
    print(f"decision records found: {found}")
    print(f"  cite their sources:   {clean}")
    print(f"  cite nothing:         {len(bad)}")
    for p, why in sorted(bad):
        print(f"    {p}\n      {'; '.join(why)}")
    return 0  # report mode never fails a build


def selftest() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        if not cond:
            print(f"FAIL: {name}")
            ok = False

    good = ("# 0001. A decision\n\n## Sources\n\n- https://a.example/x\n- https://b.example/y\n")
    check("a record citing two sources passes", failures(good) == [])
    check("headings at other levels count", failures(good.replace("## Sources", "### Sources")) == [])

    check("no Sources heading fails",
          "no '## Sources' heading" in failures("# d\n\nhttps://a.example/x\nhttps://b.example/y\n"))
    check("a heading with no URLs fails", failures("# d\n\n## Sources\n\nnone\n") != [])
    check("one source is not enough",
          failures("# d\n\n## Sources\n\n- https://a.example/x\n") != [])
    check("the same URL twice is one source",
          failures("# d\n\n## Sources\n\n- https://a.example/x\n- https://a.example/x\n") != [])

    check("a real ADR path is recognised", is_adr("/r/docs/decisions/0001-thing.md"))
    check("an adr-prefixed directory counts", is_adr("/r/docs/adrs/0002-thing.md"))
    check("the template is not graded", not is_adr("/r/docs/decisions/template.md"))
    check("an ordinary doc is not graded", not is_adr("/r/docs/architecture.md"))

    print("PASS: it refuses a record citing nothing and permits one citing two."
          if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--sweep" in sys.argv:
        roots = [a for a in sys.argv[1:] if not a.startswith("-")]
        return sweep(roots or [os.path.expanduser("~/dev/code")])
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
