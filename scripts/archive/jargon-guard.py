#!/usr/bin/env python3
"""Refuse a reply that talks to the founder in jargon.

WHY THIS IS A SCRIPT AND NOT A RULE. The rule already existed. `~/.claude/CLAUDE.md` has carried
the "Plain English - say it straight" section since 2026-08-16, written after the founder said
"you sound drunk". On 2026-08-20 I wrote him three bullet points containing "client-bundled
module", "source scan", "drift test", "path filter" and "unrefed", and he replied "not sure wht y
of thi neans", then asked "why dont we avoid jargon as law". It was already law. A rule I can
read and still break is the floor, so this is the machine that refuses it.

WHAT IT READS. The Stop hook payload names the transcript. This takes the last assistant message
in it and scans the text ABOVE the first `---` line, because that is the part written for a
person. Below the fold is evidence, where a flag, a file path and a command name are wanted.

WHAT IT SKIPS. Fenced code, inline backticks, URLs and file paths. A word inside `code` is a
name, not jargon.

WHY THE WORD LIST IS SHORT. Every entry is a word I actually used on the founder, or one of the
same kind. A long list invents offences, gets false positives, and an unsatisfiable guard gets
uninstalled. Add to it when a real reply earns it, not from a thesaurus.

WHY IT REFUSES EVERY TIME. Until crew#603 (2026-08-28) it stopped after three blocks a session
and passed a repeated text; a guard that can be worn down is an honor system. Rewrite to pass.

  python3 jargon-guard.py --selftest    # proves it blocks the real reply and passes the rewrite
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


#: word -> what to say instead. The right-hand side is printed, so it has to be usable as-is.
JARGON = {
    "no-op": "does nothing",
    "idempotent": "safe to run twice",
    "seam": "the place where X plugs in",
    "wire format": "the shape of the data on the network",
    "client-bundled": "code that ships to the browser",
    "source scan": "a test that reads the source",
    "drift test": "a test that fails if the two copies stop matching",
    "path filter": "the rule that decides which tests CI runs",
    "unrefed": "does not hold the process open",
    "unref": "does not hold the process open",
    "fan-out": "run several at once",
    "backpressure": "slowing down when the far end is full",
    "back-pressure": "slowing down when the far end is full",
    "orthogonal": "unrelated",
    "vacuous": "passes without checking anything",
    "blast radius": "how much it breaks",
    "footgun": "easy to get wrong",
    "affordance": "the thing you can click",
    "surface area": "how much of it is exposed",
    "hydrate": "fill in on the browser side",
    "rehydrate": "fill in on the browser side",
    "monotonic": "only ever goes up",
    "hermetic": "runs the same everywhere",
    "memoize": "remember the answer",
    "thunk": "a function you call later",
}

#: The founder said "plain englioh always etf" on 2026-08-22, after a reply that used none of the
#: words above. What he was correcting was shape, not vocabulary, and `~/.claude/AGENTS.md` under
#: "Plain English" already bans these three. Each one below is a sentence I actually wrote to him.
#: Keep it this short for the same reason the word list is short.
SHAPES = [
    (re.compile(r"^\s*(?:DONE|WORKING|BLOCKED)\s*:\s*(?:it'?s|they'?re|that'?s|this is|there'?s|there is)\s+not\b", re.I),
     "opens by saying what the thing is not",
     "open with what it is: \"run_v2.py is an ungrounded prototype\""),
    (re.compile(r"\bthe\s+(?:engine|system|code|pipeline|suite|script|tool|test)\s+(?:exists to|wants|thinks|knows|believes|decides|likes|hates|feels|remembers)\b", re.I),
     "gives software a mind",
     "say who did what: \"we built the engine to ...\""),
    (re.compile(r"[^\n]*?(?:\s-{1,2}\s|\s\u2014\s)[^\n]*?(?:\s-{1,2}\s|\s\u2014\s)"),
     "stacks dashes in one line",
     "two short sentences instead"),
]

FENCE = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`]*`")
URL = re.compile(r"https?://\S+")
PATH = re.compile(r"\S*/\S*")


def strip_code(text: str) -> str:
    """Remove everything that is a name rather than prose."""
    text = FENCE.sub(" ", text)
    text = INLINE.sub(" ", text)
    text = URL.sub(" ", text)
    return PATH.sub(" ", text)


def above_the_fold(text: str) -> str:
    """The part written for a person. A line that is only dashes starts the evidence."""
    out = []
    for line in text.splitlines():
        if re.fullmatch(r"\s*-{3,}\s*", line):
            break
        out.append(line)
    return "\n".join(out)


def offences(text: str) -> list[tuple[str, str]]:
    prose = strip_code(above_the_fold(text))
    found = []
    for word, plain in JARGON.items():
        pattern = r"(?<![\w-])" + re.escape(word) + r"(?![\w-])"
        if re.search(pattern, prose, re.I):
            found.append((word, plain))
    for pattern, name, plain in SHAPES:
        if pattern.search(prose):
            found.append((name, plain))
    return found


def last_assistant_text(transcript: Path) -> str:
    """The final assistant message. Text blocks only: thinking is not shown to the founder."""
    text = ""
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            parts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                text = joined
    return text



def report(found: list[tuple[str, str]]) -> str:
    lines = ["PLAIN ENGLISH BROKEN IN A REPLY TO THE FOUNDER. He should not have to decode it."]
    for word, plain in found:
        lines.append('  "%s"  ->  say "%s"' % (word, plain))
    lines.append("")
    lines.append("Law: ~/.claude/CLAUDE.md, \"Plain English - say it straight\". His words were "
                 "\"you sound drunk\" and \"not sure wht y of thi neans\".")
    lines.append("Rewrite the text above the --- line and stop again. Below the fold is "
                 "evidence and is not checked, and anything in backticks is a name, not jargon.")
    return "\n".join(lines)


def selftest() -> int:
    real = ("Three things worth a reviewer's eye: the client-bundled module never sees the key, "
            "a source scan proves it, and the drift test is single-lane because of the CI path "
            "filter. The timer is unrefed.")
    rewrite = ("Three things worth a reviewer's eye: the browser never gets the key, a test "
               "reads the source and fails if anything imports it, and the copy check only runs "
               "in one of the two apps. The timer does not hold the build open.")
    checks = []

    got = {w for w, _ in offences(real)}
    checks.append(("blocks the real reply",
                   got == {"client-bundled", "source scan", "drift test", "path filter",
                           "unrefed"}, sorted(got)))
    checks.append(("passes the rewrite", offences(rewrite) == [], offences(rewrite)))
    checks.append(("code is not jargon", offences("The `no-op` flag is set.") == [], None))
    checks.append(("a path is not jargon", offences("See src/seam/thunk.ts for it.") == [], None))
    checks.append(("below the fold is free",
                   offences("All good.\n\n---\n\nThe drift test is idempotent.") == [], None))
    checks.append(("a longer word is not a hit", offences("The seamstress arrived.") == [], None))
    checks.append(("hyphenated neighbours miss",
                   offences("A no-operation call.") == [], None))
    checks.append(("a real hit inside a sentence",
                   [w for w, _ in offences("This is idempotent.")] == ["idempotent"], None))
    checks.append(("the report names the word",
                   'idempotent' in report(offences("This is idempotent.")), None))

    # The reply the founder corrected with "plain englioh always etf" on 2026-08-22.
    shaped = ("DONE: they're not two versions of the same thing. `run.py` is the engine. "
              "`run_v2.py` is an ungrounded prototype of the moat - the thing the engine "
              "exists to not be.")
    shaped_fix = ("DONE: `run.py` is the engine and `run_v2.py` is an ungrounded prototype. "
                  "We built the engine to ground every claim in retrieval. The prototype "
                  "retrieves nothing.")
    got_shapes = {w for w, _ in offences(shaped)}
    checks.append(("blocks the shapes he corrected",
                   got_shapes == {"opens by saying what the thing is not", "gives software a mind"},
                   sorted(got_shapes)))
    checks.append(("passes the shape rewrite", offences(shaped_fix) == [], offences(shaped_fix)))
    checks.append(("stacked dashes are a hit",
                   [w for w, _ in offences("DONE: the fix landed - the gate is green - we can ship.")]
                   == ["stacks dashes in one line"], None))
    checks.append(("one dash is fine",
                   offences("DONE: the fix landed - the gate is green.") == [], None))
    checks.append(("a plain negative sentence is fine",
                   offences("DONE: the scheduler is not running yet.") == [], None))

    bad = [(name, extra) for name, ok, extra in checks if not ok]
    for name, extra in bad:
        print("FAIL %s %r" % (name, extra), file=sys.stderr)
    if bad:
        return 1
    print("jargon-guard selftest: %d/%d passed" % (len(checks), len(checks)))
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}

    path = payload.get("transcript_path") or ""
    if not path or not os.path.exists(path):
        return 0  # a probe that cannot run means PASS
    try:
        text = last_assistant_text(Path(path))
    except OSError:
        return 0
    if not text:
        return 0

    found = offences(text)
    if not found:
        return 0

    # crew#603 (founder 2026-08-28): the three-blocks-a-session cap and the pass-on-repeat are
    # gone. A guard that can be worn down is an honor system; the fourth refusal is the first.
    print(report(found), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
