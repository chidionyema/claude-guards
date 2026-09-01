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

    secret-scrub.py            redact, print counts, exit 0; live transcripts are read from
                               where the last run stopped (crew#787)
    secret-scrub.py --full     the same, reading every live transcript from the start
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

import json
import os
import pathlib
import re
import sys
import tempfile

HOME = pathlib.Path.home()

# crew#787 (2026-09-01): every Stop of every session re-read every transcript under
# ~/.claude/projects (844 MB, largest 88 MB) through 13 patterns, took minutes, outlived the
# hook wrapper and piled up as orphans until the Mac's load average was 760. A transcript is only
# ever appended to, so the scrub remembers how far it has read each live file and scans the new
# bytes only, with an overlap longer than any credential so a value split across two runs is still
# seen. A file that shrank was rewritten and is read from the start. `--check` and `--full` read
# everything. The state file is the only thing this adds; a missing or broken one means a full
# scan, never a skipped one.
OFFSETS = pathlib.Path(os.environ.get("SECRET_SCRUB_OFFSETS")
                       or str(HOME / ".claude" / "state" / "secret-scrub-offsets.json"))
OVERLAP = 4096

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
    ("GOOGLE",      re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # Added 2026-08-24, after a session ran `docker compose config` on a stack whose
    # `env_file` is the estate .env. Compose expands every value inline, so one command put
    # 63 occurrences of 20 live credentials into the session transcript. Each shape below is
    # one that was in that output and that nothing here matched.
    ("STRIPE",      re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}\b")),
    ("STRIPE_WH",   re.compile(r"\bwhsec_[A-Za-z0-9]{20,}\b")),
    ("FLY",         re.compile(r"FlyV1 fm2_[A-Za-z0-9+/=,_\-]{40,}")),
    ("DEEPSEEK",    re.compile(r"\bsk-[0-9a-f]{32}\b")),
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

# The same job, for files something may be APPENDING to right now -- the session transcript
# above all, which is the single largest thing an agent writes and was missing from the list
# until 2026-08-24.
#
# They are a separate list because they cannot be rewritten the same way. `rewrite()` below
# ends in os.replace, and a rename swaps the inode: the writer still holds a descriptor on the
# old one, so every later line of the session goes to an unlinked file and the transcript
# stops mid-sentence. These are patched IN PLACE instead, overwriting each match with the same
# number of bytes, which leaves every offset and the file length untouched.
LIVE_GLOBS = [
    ".claude/projects/*/*.jsonl",
    ".claude/projects/*/tool-results/*",
]

# Shapes cannot describe an opaque credential. `R2_SECRET_ACCESS_KEY` is 64 hex characters and
# `CONTROL_CENTER_PASSWORD` is 32 of base62 -- write a pattern loose enough to catch either and
# it eats git hashes, and a scrubber that corrupts files gets turned off (see the module note).
#
# So the second half of this is exact-value matching: read the .env files the estate actually
# keeps, take every value long enough to be a credential, and delete those exact strings. No
# false positives are possible, because the string is known to BE a live secret. This is what
# catches the ones no shape above will ever match.
VALUE_SOURCES = [
    ".env",
    "dev/code/*/.env",
    ".config/*/secrets.sh",
]
MIN_VALUE_LEN = 20
# Publishable by design -- Stripe prints them in its own docs and they ship in web bundles.
VALUE_SKIP_PREFIXES = ("pk_live_", "pk_test_", "http://", "https://")
SECRET_KEY_WORDS = (
    "KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PEM", "CREDENTIAL", "WEBHOOK", "DSN",
)

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


def live_targets() -> list[pathlib.Path]:
    """LIVE_GLOBS, filtered the same way targets() filters TARGET_GLOBS."""
    out: list[pathlib.Path] = []
    for g in LIVE_GLOBS:
        for p in HOME.glob(g):
            if not p.is_file() or p.is_symlink():
                continue
            if any(part in EXCLUDE_PARTS for part in p.parts):
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            out.append(p)
    return sorted(set(out))


def known_values() -> list[bytes]:
    """Every live credential VALUE the estate keeps, as bytes to search for.

    Reads the .env files rather than being told what to look for, so a key added tomorrow is
    covered tomorrow with nothing to update here.
    """
    vals: set[bytes] = set()
    for g in VALUE_SOURCES:
        for p in HOME.glob(g):
            if not p.is_file() or p.is_symlink():
                continue
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.replace("export ", "").strip().upper()
                v = v.strip().strip('"').strip("'")
                if len(v) < MIN_VALUE_LEN:
                    continue
                if v.startswith(VALUE_SKIP_PREFIXES):
                    continue
                # The KEY has to look like a credential. Without this, `RUNNER_LABELS` and
                # every other long config value gets deleted out of transcripts too, and a
                # scrubber that mangles ordinary text is one somebody switches off.
                if not any(w in k for w in SECRET_KEY_WORDS):
                    continue
                vals.add(v.encode())
    return sorted(vals, key=len, reverse=True)


def load_offsets() -> dict[str, list[int]]:
    """path -> [bytes covered, mtime_ns at the time]. An older int-only row still loads."""
    try:
        raw = json.loads(OFFSETS.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[int]] = {}
    for k, v in raw.items():
        try:
            out[k] = [int(v[0]), int(v[1])] if isinstance(v, list) else [int(v), 0]
        except (TypeError, ValueError, IndexError):
            continue
    return out


def save_offsets(offsets: dict[str, list[int]]) -> None:
    try:
        OFFSETS.parent.mkdir(parents=True, exist_ok=True)
        tmp = OFFSETS.with_suffix(".tmp")
        tmp.write_text(json.dumps(offsets, separators=(",", ":")))
        os.replace(tmp, OFFSETS)
    except OSError:
        pass


SKIP = -1


def resume_from(path: pathlib.Path, offsets: dict[str, list[int]]) -> int:
    """Where the incremental scan of `path` starts: SKIP when the file has the size and mtime
    the last run recorded (it is not even opened: 21,500 tool-result files made a 59 s run of
    that alone); the last scanned length minus OVERLAP; or 0 when the file is new, shrank, or
    was never finished."""
    try:
        st = path.stat()
    except OSError:
        return 0
    seen, stamp = offsets.get(str(path), [0, 0])
    if seen <= 0 or seen > st.st_size:
        return 0
    if seen == st.st_size and stamp == st.st_mtime_ns:
        return SKIP
    return max(0, seen - OVERLAP)


def patch_in_place(path: pathlib.Path, values: list[bytes], check_only: bool,
                   start_at: int = 0) -> tuple[int, int]:
    """Overwrite matches with the same number of bytes. Safe on a file being appended to.

    Same-length is the whole point: the file's length and every byte offset in it are
    unchanged, so a process holding it open and writing to the end never notices.
    Reads from `start_at`; answers (matches, bytes of the file covered by this read).
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(start_at)
            data = fh.read()
    except OSError:
        return 0, 0
    end = start_at + len(data)

    spans: list[tuple[int, int]] = []
    for v in values:
        start = 0
        while (i := data.find(v, start)) >= 0:
            spans.append((start_at + i, len(v)))
            start = i + len(v)
    for _name, rx in PATTERNS:
        for m in rx.finditer(data.decode("latin-1")):
            spans.append((start_at + m.start(), m.end() - m.start()))

    # A value match and a shape match can cover the same bytes -- `sk_live_...` is both a
    # known value and the STRIPE pattern. Overwriting twice is harmless, but counting twice is
    # a number that is not true, so merge overlaps before reporting one.
    merged: list[tuple[int, int]] = []
    for off, ln in sorted(spans):
        if merged and off <= merged[-1][0] + merged[-1][1]:
            prev_off, prev_ln = merged[-1]
            merged[-1] = (prev_off, max(prev_ln, off + ln - prev_off))
        else:
            merged.append((off, ln))
    spans = merged

    if not spans or check_only:
        return len(spans), end

    with open(path, "r+b") as f:
        for off, ln in spans:
            f.seek(off)
            f.write(b"X" * ln)
        f.flush()
        os.fsync(f.fileno())
    return len(spans), end


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


def run(check_only: bool, full: bool = False) -> int:
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
    # The append-safe half. Separate loop because these are patched in place, not rewritten.
    values = known_values()
    live_hits = 0
    live_files = 0
    incremental = not (check_only or full)
    offsets = load_offsets() if incremental else {}
    live = live_targets()
    for p in live:
        start_at = resume_from(p, offsets) if incremental else 0
        if start_at == SKIP:
            continue
        n, covered = patch_in_place(p, values, check_only, start_at)
        if incremental and covered:
            try:
                offsets[str(p)] = [covered, p.stat().st_mtime_ns]
            except OSError:
                pass
        if not n:
            continue
        live_hits += n
        live_files += 1
        rel = str(p).replace(str(HOME), "~")
        print(f"{'FOUND' if check_only else 'scrubbed'} {n} occurrence(s) in {rel}")
    total += live_hits
    touched += live_files
    if incremental:
        keep = {str(p) for p in live}
        save_offsets({k: v for k, v in offsets.items() if k in keep})

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
        "GOOGLE": "AIza" + "S" * 35,
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
          all(json.loads(line) for line in after.splitlines() if line.strip()), True)

    # The real secret store is never a target.
    names = [p.name for p in targets()]
    check("secrets.sh is never a target", any(n.startswith("secrets.sh") for n in names), False)

    print("secret-scrub selftest", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    return run(check_only="--check" in sys.argv, full="--full" in sys.argv)


if __name__ == "__main__":
    # A Stop hook must never break the session it runs in.
    try:
        sys.exit(main())
    except Exception as exc:                                        # noqa: BLE001
        print(f"[secret-scrub] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)
