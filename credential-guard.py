#!/usr/bin/env python3
"""Refuse a credential value in a reply or in a GitHub comment body (crew#407, LAW 21).

Incident 2026-08-27 (crew#407): a session sent the router console password to the founder's
Telegram. claude-guards#113 made every Telegram sender refuse a credential shape. Two paths
stayed open: the reply itself, which the founder reads in the terminal and which the transcript
keeps forever, and `gh issue comment` / `gh pr comment` bodies, which land on a public host.
The same shape test (estate_alert.credential_shape) now runs on both:

    Stop            the last assistant message of the transcript
    PreToolUse Bash a command that writes an issue, pull request or comment through gh, and
                    every --body-file / -F it names

Refusal is exit 2 with the kind and length of the match on stderr. The value is never printed.
A value that was already typed is a rotation, not a rewrite: the refusal says so.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import shlex
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "estate"))
import estate_alert  # noqa: E402

WRITES = re.compile(r"\bgh\s+(?:issue|pr)\s+(?:comment|create|edit)\b|\bgh\s+api\b[^\n]*\bcomments\b")


def _last_assistant_text(path: str) -> str:
    spec = importlib.util.spec_from_file_location("close_guard", HERE / "close-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.last_assistant_text(pathlib.Path(path))


def body_files(cmd: str, cwd: str) -> list[pathlib.Path]:
    """Every --body-file / -F path a gh write names, resolved against cwd."""
    out: list[pathlib.Path] = []
    for part in re.split(r"&&|\|\||;|\n", cmd):
        try:
            argv = shlex.split(part)
        except ValueError:
            continue
        for i, tok in enumerate(argv):
            val = ""
            if tok in ("--body-file", "-F") and i + 1 < len(argv):
                val = argv[i + 1]
            elif tok.startswith("--body-file="):
                val = tok.split("=", 1)[1]
            if val and val != "-":
                out.append(pathlib.Path(os.path.expanduser(val)) if val.startswith(("/", "~")) else pathlib.Path(cwd) / val)
    return out


def gh_write_text(cmd: str, cwd: str) -> str:
    """The text a gh write would publish: the command itself (bodies, heredocs) plus body files."""
    if not WRITES.search(cmd):
        return ""
    text = cmd
    for p in body_files(cmd, cwd):
        try:
            text += "\n" + p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return text


def verdict(text: str, where: str) -> str | None:
    hit = estate_alert.credential_shape(text)
    if not hit:
        return None
    m = None
    for rx in estate_alert._CREDENTIAL_SHAPES:
        m = rx.search(text)
        if m:
            break
    n = len(m.group(0)) if m else 0
    return (f"REFUSED: {where} carries a credential-shaped value ({n} chars). A secret value never "
            "appears in a reply, an issue, a pull request or a chat (LAW 21, crew#407). Name where it "
            "lives (vault entry, sops path) instead. If the value was already sent anywhere, rotate it.")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    event = payload.get("hook_event_name") or ""
    if event == "Stop":
        path = payload.get("transcript_path") or ""
        if not path or not os.path.exists(path):
            return 0
        try:
            text = _last_assistant_text(path)
        except OSError:
            return 0
        msg = verdict(text, "the reply")
    elif event == "PreToolUse":
        if payload.get("tool_name") != "Bash":
            return 0
        cmd = str((payload.get("tool_input") or {}).get("command", ""))
        cwd = str(payload.get("cwd") or os.getcwd())
        msg = verdict(gh_write_text(cmd, cwd), "the gh comment/body")
    else:
        return 0
    if not msg:
        return 0
    sys.stderr.write(msg + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
