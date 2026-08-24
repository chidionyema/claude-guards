#!/usr/bin/env python3
"""Parse a config file the way the service that reads it parses it.

One implementation, imported by both config-syntax-guard.py (blocks the write)
and config-syntax-sweep.py (counts what is already broken). Two implementations
of one check is the failure LAW 3 names, so the routing lives here only.

WHY THIS EXISTS
---------------
2026-08-24. A double hyphen inside an XML comment in
`idp/observability/clickhouse-low-memory.xml` is illegal, so ClickHouse refused
the entire file with `SAXParseException: Invalid token` and crash-looped.
`langfuse-web` and `langfuse-worker` have a depends_on condition on clickhouse
being healthy, so neither was ever created -- `docker ps -a` showed them as
`Created`, which reads like "not started yet" and not like "blocked upstream".
Three hours. Writing the comment that explained the fix introduced a second
double hyphen in the same comment and broke the file again.

THE CLASS
---------
A config file a service reads at startup, whose syntax nothing checks before
that service starts. Not "an XML comment". The XML file was one instance.

WHY NOT A NAIVE PARSE
---------------------
A guard that refuses correct work is an outage (LAW 38). Grading the file
extension instead of the consumer's actual reader flagged 5 healthy files out
of 12 on the first estate sweep:

  tsconfig.json is JSONC. TypeScript and VS Code strip // comments and trailing
  commas before parsing, so strict json.loads rejecting them says nothing about
  whether TypeScript can read the file.

  launchSettings.json is written by Visual Studio with a UTF-8 BOM, and .NET
  reads it with utf-8-sig. Reading it as plain utf-8 fails on a working file.

  A .json file holding one document per line is NDJSON. Its consumer reads it a
  line at a time; json.loads over the whole file is the wrong reader.
"""
from __future__ import annotations

import fnmatch
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import yaml
except ImportError:  # a guard that cannot read its evidence says so
    yaml = None  # type: ignore[assignment]

#: Files whose consumer accepts comments and trailing commas.
JSONC_GLOBS = ("tsconfig*.json", "jsconfig*.json", "devcontainer.json", "*.jsonc")
JSONC_DIRS = (".vscode", ".devcontainer")

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def strip_jsonc(src: str) -> str:
    """Remove // and /* */ comments and trailing commas, leaving strings alone."""
    out: list[str] = []
    i, n = 0, len(src)
    in_str = False
    while i < n:
        c = src[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if src.startswith("//", i):
            nl = src.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(c)
        i += 1
    return _TRAILING_COMMA.sub(r"\1", "".join(out))


def _check_json(src: str) -> None:
    try:
        json.loads(src)
        return
    except json.JSONDecodeError as strict_err:
        lines = [ln for ln in src.splitlines() if ln.strip()]
        if len(lines) > 1:
            try:
                for ln in lines:
                    json.loads(ln)
                return  # NDJSON: the consumer reads it a line at a time
            except json.JSONDecodeError:
                pass
        raise strict_err


def _check_jsonc(src: str) -> None:
    json.loads(strip_jsonc(src))


def _check_yaml(src: str) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed, so this file was NOT checked")
    list(yaml.safe_load_all(src))


def _check_toml(src: str) -> None:
    tomllib.loads(src)


def _check_xml(src: str) -> None:
    # expat applies the same comment and token rules ClickHouse's Poco parser
    # applies, including rejecting a double hyphen inside a comment.
    ET.fromstring(src)


def checker_for(file_path: str | Path):
    """Return the parse function for this path, or None if it is not a config file."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix in (".yml", ".yaml"):
        return _check_yaml
    if suffix == ".toml":
        return _check_toml
    if suffix == ".xml":
        return _check_xml
    if suffix in (".json", ".jsonc"):
        if any(fnmatch.fnmatch(path.name, g) for g in JSONC_GLOBS):
            return _check_jsonc
        if path.parent.name in JSONC_DIRS:
            return _check_jsonc
        return _check_json
    return None


def problem(file_path: str | Path, content: str) -> str | None:
    """None when the consumer can read this content. Otherwise the parser's error."""
    check = checker_for(file_path)
    if check is None:
        return None
    try:
        check(content)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def read_text(path: Path) -> str:
    # utf-8-sig also decodes plain utf-8, so it is the strictly wider reader.
    return path.read_text(encoding="utf-8-sig")
