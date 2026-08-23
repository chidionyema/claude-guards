#!/usr/bin/env python3
"""Keep live credentials out of the files agents and shells write.

LAW 21 says a secret value never appears anywhere it can be read again. On 2026-08-23 the
estate audit found two, and a wider scan found more:

    ~/.claude/history.jsonl      8 occurrences, 4 distinct keys
    ~/.zsh_history              22 occurrences
    5 checkpoint/recovery .md    5 occurrences

None of them was written on purpose. A key gets pasted into a prompt or typed on a command
line, and three different logs keep a copy forever. Detection already existed: estate_audit.py
had been reporting the history.jsonl pair hourly. Nothing removed them, which is LAW 28 --
an instrument nobody reads.

This is the remover. It runs on Stop, so a key pasted in a session is gone by the end of it.

    secret-scrub.py            redact, print counts, exit 0
    secret-scrub.py --check    report only, change nothing, exit 1 if anything is found
    secret-scrub.py --selftest prove the patterns and the rewrite on a temp file

What it never touches, on purpose:
    ~/.config/*/secrets.sh     the files whose job is to hold secrets, already mode 600
    ~/.hermes/hermes-agent/    upstream test fixtures: sk-ant-api03-explicit, ghp_abc123
A scrubber that eats the real secret store, or that rewrites a vendored test corpus, gets
turned off, and a scrubber that is turned off protects nothing.

It only ever removes. It never prints a secret, only its kind and length.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

HOME = pathlib.Path.home()

# Anchored on a provider prefix and a real length. A bare `sk-[A-Za-z0-9]{40,}` also matches
# ordinary base64 in a log, and a scrubber with false positives corrupts files.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ANTHROPIC",   re.compile(r"sk-ant-(?:api|oat)[A-Za-z0-9_\-]{20,}")),
    ("OPENROUTER",  re.compile(r"sk-or-v1-[A-Za-z0-9_\-]{20,}")),
    ("CP",          re.compile(r"sk-cp-[A-Za-z0-9_\-]{20,}")),
    ("OPENAI",      re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{40,}\b")),
    ("HUGGINGFACE", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("GITHUB",      re.compile(r"\b(?:ghp_[A-Za-z0-9]{34,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("AWS",         re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SLACK",       re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{20,}\b")),
]

# Files that agents and shells write. Globs are relative to $HOME.
TARGET_GLOBS = [
    ".claude/history.jsonl",
    ".zsh_history",
    ".bash_history",
    ".claude/projects/*/checkpoints/*.md",
    ".claude/projects/*/CHECKPOINT*.md",
    ".claude/state/logs/*.log",
]

# Never rewritten. Order matters only for readability.
EXCLUDE_PARTS = ("hermes-agent", "node_modules", ".git", "__pycache__", "site-packages")
EXCLUDE_NAMES = ("secrets.sh",)

MAX_BYTES = 200 * 1024 * 1024


def targets() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for g in TARGET_GLOBS:
        for p in HOME.glob(g):
            if not p.is_file():
                continue
            if any(part in EXCLUDE_PARTS for part in p.parts):
                continue
            if p.name in EXCLUDE_NAMES or p.name.startswith("secrets.sh"):
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            out.append(p)
    return sorted(set(out))


def scan_text(text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for name, rx in PATTERNS:
        n = len(rx.findall(text))
        if n:
            found[name] = n
    return found


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    out, counts = text, {}
    for name, rx in PATTERNS:
        out, n = rx.subn(lambda m: f"[REDACTED-{name}-{len(m.group(0))}CHARS]", out)
        if n:
            counts[name] = n
    return out, counts


def rewrite(path: pathlib.Path, text: str) -> None:
    """Atomic, mode preserved. A half-written history file is worse than a leaked one."""
    mode = path.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    os.close(fd)
    tmp_p = pathlib.Path(tmp)
    try:
        tmp_p.write_text(text, errors="surrogateescape")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp_p.unlink(missing_ok=True)
        raise


def run(check_only: bool) -> int:
    total = 0
    touched = 0
    for p in targets():
        try:
            text = p.read_text(errors="surrogateescape")
        except OSError:
            continue
        found = scan_text(text)
        if not found:
            continue
        rel = str(p).replace(str(HOME), "~")
        total += sum(found.values())
        if check_only:
            print(f"FOUND {found} in {rel}")
            continue
        new, counts = redact_text(text)
        # A redaction that changes the line count has eaten a newline. Refuse it.
        if new.count("\n") != text.count("\n"):
            print(f"REFUSED {rel}: line count would change", file=sys.stderr)
            continue
        rewrite(p, new)
        touched += 1
        print(f"scrubbed {counts} from {rel}")
    if check_only:
        print(f"secret-scrub: {total} occurrence(s) in files that should hold none")
        return 1 if total else 0
    if total:
        print(f"secret-scrub: removed {total} occurrence(s) from {touched} file(s)")
    return 0


def selftest() -> int:
    import json

    d = pathlib.Path(tempfile.mkdtemp())
    ok = True

    def check(name: str, got, want) -> None:
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  ok   {name}")

    # Every pattern fires on a realistic value.
    samples = {
        "ANTHROPIC": "sk-ant-api03-" + "A" * 40,
        "OPENROUTER": "sk-or-v1-" + "b" * 40,
        "CP": "sk-cp-" + "C" * 40,
        "OPENAI": "sk-proj-" + "d" * 48,
        "HUGGINGFACE": "hf_" + "e" * 34,
        "GITHUB": "ghp_" + "f" * 36,
        "AWS": "AKIA" + "G" * 16,
        "SLACK": "xoxb-" + "1" * 30,
    }
    for kind, value in samples.items():
        got, counts = redact_text(f"export K={value}\n")
        check(f"{kind} redacted", value in got, False)
        check(f"{kind} labelled", list(counts), [kind])

    # Ordinary text survives untouched. A scrubber with false positives corrupts files.
    for benign in ("a normal sentence", "sk-something-short", "hf_tooShort",
                   "commit 8262a28b0f1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e"):
        got, counts = redact_text(benign)
        check(f"benign kept: {benign[:22]}", (got, counts), (benign, {}))

    # A real file is rewritten in place, line count and mode preserved.
    f = d / "history.jsonl"
    f.write_text(json.dumps({"display": "export A=sk-ant-api03-" + "Z" * 40}) + "\n"
                 + json.dumps({"display": "ls -la"}) + "\n")
    os.chmod(f, 0o600)
    before = f.read_text()
    new, counts = redact_text(before)
    rewrite(f, new)
    after = f.read_text()
    check("rewrite removed the key", "sk-ant-api03" in after, False)
    check("rewrite kept the line count", after.count("\n"), before.count("\n"))
    check("rewrite kept mode 600", oct(f.stat().st_mode & 0o777), "0o600")
    check("rewrite left other lines alone", "ls -la" in after, True)
    check("every line still parses as json",
          all(json.loads(l) for l in after.splitlines() if l.strip()), True)

    # The real secret store is never a target.
    names = [p.name for p in targets()]
    check("secrets.sh is never a target", any(n.startswith("secrets.sh") for n in names), False)

    print("secret-scrub selftest", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    return run(check_only="--check" in sys.argv)


if __name__ == "__main__":
    # A Stop hook must never break the session it runs in.
    try:
        sys.exit(main())
    except Exception as exc:                                        # noqa: BLE001
        print(f"[secret-scrub] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)
