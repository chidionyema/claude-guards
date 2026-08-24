#!/usr/bin/env python3
"""PreToolUse guard: refuse a write that would leave a config file unparseable.

WHY THIS EXISTS
---------------
2026-08-24, founder: "add a law if you ake a istake, you need to ensure no agent
sessionn can ever nnake that nistake again ever a dprove it ehaustively".

The mistake: a double hyphen inside an XML comment in
`idp/observability/clickhouse-low-memory.xml`. A double hyphen is illegal there,
so ClickHouse refused the whole file with `SAXParseException: Invalid token` and
crash-looped. `langfuse-web` and `langfuse-worker` wait on clickhouse being
healthy, so neither was ever created, and `docker ps -a` showed them as
`Created` -- which reads like "not started yet", not like "blocked upstream".
Three hours. The fix, written into the comment explaining the fix, contained a
second double hyphen and broke the file again.

The first repair was `xmllint --noout` in `bin/langfuse-up`. That is one script
in one repo. It protects `bin/langfuse-up` and nothing else, and my memory of
the incident dies with my context. Six sessions run on this machine and none can
see another's context. LAW 45 is the rule that this is not a closed mistake.

THE RULE
--------
Every session writes files through Write and Edit. A Write or Edit that would
leave a `.xml`, `.yml`, `.yaml`, `.json`, `.jsonc` or `.toml` file in a state its
consumer cannot parse is refused, and the message is the parser's own error with
the line and column. The check runs before the bytes land, in every session, so
the class cannot recur rather than being caught later by a reviewer.

Each file is parsed the way its actual consumer parses it -- tsconfig.json as
JSONC, a BOM-prefixed file as utf-8-sig, a line-per-document .json as NDJSON.
The routing is in config_syntax.py and is shared with config-syntax-sweep.py,
because two implementations of one check is the failure LAW 3 names.

HOW IT FAILS
------------
Open. An unparseable payload, a missing file, a missing parser library, any
exception -> exit 0 and the write proceeds. A guard that wedges every session is
a worse outage than the defect it prevents (LAW 38). An Edit whose old_string is
not found in the file is left alone: the Edit tool will reject it anyway, and
guessing the final content would be grading a proxy.

THE ESCAPE
----------
Put `CONFIG-SYNTAX-OK` in the content. A template holding deliberate
placeholders is the real case; saying so out loud is the point.

    python3 config-syntax-guard.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_syntax import ParserUnavailable, checker_for, problem  # noqa: E402

ESCAPE = "CONFIG-SYNTAX-OK"


def final_content(tool: str, ti: dict) -> str | None:
    """The bytes the file will hold after this call, or None if not knowable."""
    path = ti.get("file_path") or ""
    if not path:
        return None
    if tool == "Write":
        return ti.get("content")
    if tool in ("Edit", "MultiEdit"):
        try:
            src = Path(path).expanduser().read_text(encoding="utf-8-sig")
        except OSError:
            return None  # new file, or unreadable: nothing to reconstruct from
        edits = ti.get("edits") or [ti]
        for e in edits:
            old = e.get("old_string")
            new = e.get("new_string")
            if old is None or new is None or old not in src:
                return None
            src = src.replace(old, new) if e.get("replace_all") else src.replace(old, new, 1)
        return src
    return None


def verdict(tool: str, ti: dict) -> str | None:
    """The refusal message, or None to let the call through."""
    path = ti.get("file_path") or ""
    if checker_for(path) is None:
        return None
    content = final_content(tool, ti)
    if content is None or ESCAPE in content:
        return None
    try:
        why = problem(path, content)
    except ParserUnavailable:
        # No parser for this format on this interpreter. The guard has no
        # evidence, so it permits the write rather than refusing correct
        # work (LAW 38).
        return None
    if why is None:
        return None
    return (
        f"REFUSED: this write leaves {path} unparseable by the service that reads it.\n"
        f"  {why}\n"
        "Fix the syntax and write again. A config file that a service cannot parse "
        "is refused at startup, and a container that waits on its health is never "
        "created -- which reads as 'not started yet', not as a fault.\n"
        f"If the placeholders are deliberate, put {ESCAPE} in the content."
    )


def selftest() -> int:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    good_xml = (tmp / "good.xml")
    good_xml.write_text("<clickhouse>\n  <a>1</a>\n</clickhouse>\n")

    bad_comment = '<?xml version="1.0"?>\n<!-- raise this -- and that together -->\n<c/>\n'
    ok_comment = '<?xml version="1.0"?>\n<!-- raise this and that together -->\n<c/>\n'

    cases = [
        # (tool, tool_input, should_refuse)
        # the incident itself, in both directions
        ("Write", {"file_path": "/x/clickhouse.xml", "content": bad_comment}, True),
        ("Write", {"file_path": "/x/clickhouse.xml", "content": ok_comment}, False),
        # the three shapes a naive checker wrongly refuses (LAW 38)
        ("Write", {"file_path": "/x/tsconfig.json",
                   "content": '{\n // a comment\n "a": 1,\n}\n'}, False),
        ("Write", {"file_path": "/x/telemetry.json",
                   "content": '{"a":1}\n{"a":2}\n'}, False),
        ("Write", {"file_path": "/x/.vscode/settings.json",
                   "content": '{\n // fine here too\n "a": 1\n}\n'}, False),
        # plain formats, both ways
        ("Write", {"file_path": "/x/compose.yml", "content": "a:\n  b: 1\n"}, False),
        ("Write", {"file_path": "/x/compose.yml", "content": "a:\n b: 1\n  c: 2\n"}, True),
        ("Write", {"file_path": "/x/p.toml", "content": '[a]\nb = 1\n'}, False),
        ("Write", {"file_path": "/x/p.toml", "content": '[a\nb = 1\n'}, True),
        ("Write", {"file_path": "/x/d.json", "content": '{"a": 1}'}, False),
        ("Write", {"file_path": "/x/d.json", "content": '{"a": 1,}'}, True),
        # files this guard has no business judging
        ("Write", {"file_path": "/x/notes.md", "content": "-- not xml --"}, False),
        ("Write", {"file_path": "/x/run.py", "content": "x = {"}, False),
        # the escape
        ("Write", {"file_path": "/x/t.xml",
                   "content": "<a> CONFIG-SYNTAX-OK {{placeholder}}"}, False),
        # Edit reconstructs the final bytes from the file on disk
        ("Edit", {"file_path": str(good_xml), "old_string": "<a>1</a>",
                  "new_string": "<a>2</a>"}, False),
        ("Edit", {"file_path": str(good_xml), "old_string": "<a>1</a>",
                  "new_string": "<a>2</b>"}, True),
        # an Edit that cannot be reconstructed is left alone, not guessed at
        ("Edit", {"file_path": str(good_xml), "old_string": "not present",
                  "new_string": "junk<"}, False),
        ("Edit", {"file_path": "/x/does-not-exist.xml", "old_string": "a",
                  "new_string": "<"}, False),
        ("Read", {"file_path": str(good_xml)}, False),
    ]
    # A case whose parser is missing on this interpreter is SKIPPED and named.
    # It must never be counted as a pass: a suite that quietly drops the cases it
    # cannot run reports green for coverage it does not have. /usr/bin/python3 is
    # 3.9.6 on this Mac and has no tomllib, which is how the .toml cases get here.
    from config_syntax import tomllib as _toml, yaml as _yaml
    missing = {".toml": _toml is None, ".yml": _yaml is None, ".yaml": _yaml is None}

    bad = skipped = 0
    for tool, ti, want in cases:
        path = ti.get("file_path", "")
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        if missing.get(ext):
            skipped += 1
            print(f"SKIP {tool} {path} -- no parser for {ext} on "
                  f"{sys.version.split()[0]}")
            continue
        got = verdict(tool, ti) is not None
        if got != want:
            bad += 1
            print(f"FAIL {tool} {path} -> refuse={got}, want={want}")
    ran = len(cases) - skipped
    print(f"{ran - bad}/{ran} passed"
          + (f", {skipped} skipped for a missing parser" if skipped else ""))
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
        msg = verdict(payload.get("tool_name") or "", payload.get("tool_input") or {})
    except Exception:
        return 0
    if not msg:
        return 0
    print(msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
