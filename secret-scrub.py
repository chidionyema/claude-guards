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

import fcntl
import json
import os
import pathlib
import re
import signal
import sys
import tempfile
import time

HOME = pathlib.Path.home()

# Budget for secret-scrub to stay within its wrapper's timeout.
# If HOOK_DEADLINE is set, the budget is min(BUDGET_S, HOOK_DEADLINE - now - 2).
# The -2s buffer ensures we exit before the wrapper kills us.
BUDGET_S = float(os.environ.get("SECRET_SCRUB_BUDGET_S") or 15)


def _budget_remaining() -> float:
    """Return remaining budget in seconds, or -1 if no budget constraint."""
    deadline = os.environ.get("HOOK_DEADLINE")
    if not deadline:
        return BUDGET_S
    try:
        remaining = float(deadline) - time.time() - 2  # 2s buffer for clean exit
        return min(BUDGET_S, max(0, remaining))
    except ValueError:
        return BUDGET_S


# Anchored on a provider prefix and a real length. A bare `sk-[A-Za-z0-9]{40,}` also matches
# ordinary base64 in a log, and a scrubber with false positives corrupts files.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ANTHROPIC", re.compile(r"sk-ant-(?:api|oat)[A-Za-z0-9_\-]{20,}")),
    ("OPENROUTER", re.compile(r"sk-or-v1-[A-Za-z0-9_\-]{20,}")),
    ("CP", re.compile(r"sk-cp-[A-Za-z0-9_\-]{20,}")),
    ("OPENAI", re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{40,}\b")),
    ("HUGGINGFACE", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    (
        "GITHUB",
        re.compile(r"\b(?:ghp_[A-Za-z0-9]{34,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    ),
    ("AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SLACK", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{20,}\b")),
    ("GOOGLE", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # Added 2026-08-24, after a session ran `docker compose config` on a stack whose
    # `env_file` is the estate .env. Compose expands every value inline, so one command put
    # 63 occurrences of 20 live credentials into the session transcript. Each shape below is
    # one that was in that output and that nothing here matched.
    ("STRIPE", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}\b")),
    ("STRIPE_WH", re.compile(r"\bwhsec_[A-Za-z0-9]{20,}\b")),
    ("FLY", re.compile(r"FlyV1 fm2_[A-Za-z0-9+/=,_\-]{40,}")),
    ("DEEPSEEK", re.compile(r"\bsk-[0-9a-f]{32}\b")),
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
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "PEM",
    "CREDENTIAL",
    "WEBHOOK",
    "DSN",
)

# Never rewritten. Order matters only for readability.
EXCLUDE_PARTS = ("hermes-agent", "node_modules", ".git", "__pycache__", "site-packages")
EXCLUDE_NAMES = ("secrets.sh",)

MAX_BYTES = 200 * 1024 * 1024

# crew#603 CP4: at Stop this runs through the one door, fail-closed, so a scan that outlives
# its budget refuses the reply. Measured 2026-08-28: a full pass over one 6.6 MB transcript
# took >300 s, which settings used to kill at 30 s and drop on the floor. So a Stop scans only
# what grew since the last pass: this ledger holds, per file, the byte count already clean.
# `--full` ignores it (the weekly pass). OVERLAP re-reads a tail so a secret split across two
# appends is still seen whole. The path takes an env override so a test can point it at a
# temp directory instead of the real ledger.
OFFSETS = pathlib.Path(
    os.environ.get(
        "SECRET_SCRUB_OFFSETS",
        str(HOME / ".claude" / "state" / "secret-scrub-offsets.json"),
    )
)
OVERLAP = 4096


def load_offsets() -> dict[str, int]:
    try:
        d = json.loads(OFFSETS.read_text())
        return {k: int(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        # A ledger another version wrote in a different shape is a fresh start, not a crash.
        return {}


def save_offsets(d: dict[str, int]) -> None:
    try:
        OFFSETS.parent.mkdir(parents=True, exist_ok=True)
        tmp = OFFSETS.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, sort_keys=True))
        os.replace(tmp, OFFSETS)
    except OSError:
        pass


# Incident 2026-09-01: every session's Stop hook started its own copy over the same files;
# four ran side by side at 70-90 % CPU each and the founder's Mac sat at load 41-88. A second
# copy has nothing to add (the offsets ledger is shared), so it leaves at once. The path takes
# an env override so a test can hold a lock of its own.
LOCK_FILE = pathlib.Path(
    os.environ.get("SECRET_SCRUB_LOCK", str(HOME / ".claude/state/secret-scrub.lock"))
)


def _hold_lock():
    """One scrubber at a time, machine-wide. Returns the open handle, or None when held."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_FILE.open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def targets() -> list[pathlib.Path]:
    """Return target files sorted largest-last so small files (history, checkpoints) are processed first.

    The offsets file already makes the next run incremental - we resume from where we left off.
    """
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
    # Largest-last: small files (history, zsh history, checkpoints) are most likely to contain
    # leaked secrets and are processed first within the budget.
    return sorted(set(out), key=lambda p: p.stat().st_size)


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


def patch_in_place(
    path: pathlib.Path, values: list[bytes], check_only: bool, start_at: int = 0
) -> int:
    """Overwrite matches with the same number of bytes. Safe on a file being appended to.

    Same-length is the whole point: the file's length and every byte offset in it are
    unchanged, so a process holding it open and writing to the end never notices.
    `start_at` scans from that byte (the incremental Stop pass); spans are file offsets.
    """
    try:
        with open(path, "rb") as f:
            f.seek(start_at)
            data = f.read()
    except OSError:
        return 0
    base = start_at

    spans: list[tuple[int, int]] = []
    for v in values:
        start = 0
        while (i := data.find(v, start)) >= 0:
            spans.append((base + i, len(v)))
            start = i + len(v)
    for _name, rx in PATTERNS:
        for m in rx.finditer(data.decode("latin-1")):
            spans.append((base + m.start(), m.end() - m.start()))

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
        return len(spans)

    with open(path, "r+b") as f:
        for off, ln in spans:
            f.seek(off)
            f.write(b"X" * ln)
        f.flush()
        os.fsync(f.fileno())
    return len(spans)


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
        out, n = rx.subn(
            lambda m, name=name: f"[REDACTED-{name}-{len(m.group(0))}CHARS]", out
        )
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
    """Run the scrubber: one copy at a time, inside its budget, dead when its wrapper is.

    Budget and orphan checks sit between files, never mid-file: a half-scrubbed file is
    worse than a late one. Whatever a cut-short pass missed is the next pass's work -- the
    offsets ledger only advances past bytes actually scanned.
    """
    lock = _hold_lock()
    if lock is None:
        print("secret-scrub: another copy is already scanning; leaving it to that one")
        return 0
    total = 0
    touched = 0
    offsets = {} if full else load_offsets()
    new_offsets: dict[str, int] = {}
    start_time = time.time()
    files_processed = 0
    budget = _budget_remaining()

    # Check if wrapper is already gone before we start
    if os.getppid() == 1:
        print("secret-scrub: wrapper gone, stopping (LAW 28)", file=sys.stderr)
        return 0

    target_list = targets()
    for p in target_list:
        # Check orphan status between files: if wrapper is gone, stop gracefully
        if os.getppid() == 1:
            print("secret-scrub: wrapper gone, stopping (LAW 28)", file=sys.stderr)
            return 0

        # Check budget between files (never mid-file)
        elapsed = time.time() - start_time
        if elapsed >= budget:
            print(
                f"secret-scrub: budget of {budget:.1f}s spent after {files_processed} of "
                f"{len(target_list)} files; the rest resumes next Stop from the offsets file",
                file=sys.stderr,
            )
            return 0

        try:
            st = p.stat()
            key = str(p)
            # Rewritten files: skip one whose size has not moved since it was last clean.
            if not full and offsets.get(key) == st.st_size:
                new_offsets[key] = st.st_size
                continue
            text = p.read_text(errors="surrogateescape")
        except OSError:
            continue
        new_offsets[key] = st.st_size
        found = scan_text(text)
        if not found:
            files_processed += 1
            continue
        rel = str(p).replace(str(HOME), "~")
        total += sum(found.values())
        if check_only:
            print(f"FOUND {found} in {rel}")
            files_processed += 1
            continue
        new, counts = redact_text(text)
        # A redaction that changes the line count has eaten a newline. Refuse it.
        if new.count("\n") != text.count("\n"):
            print(f"REFUSED {rel}: line count would change", file=sys.stderr)
            new_offsets.pop(str(p), None)
            files_processed += 1
            continue
        rewrite(p, new)
        new_offsets[str(p)] = len(new.encode("utf-8", errors="surrogateescape"))
        touched += 1
        print(f"scrubbed {counts} from {rel}")
        files_processed += 1

    # Check orphan status before live targets too
    if os.getppid() == 1:
        print("secret-scrub: wrapper gone, stopping (LAW 28)", file=sys.stderr)
        return 0

    # Check budget before live targets
    elapsed = time.time() - start_time
    if elapsed >= budget:
        print(
            f"secret-scrub: budget of {budget:.1f}s spent after {files_processed} of "
            f"{len(target_list)} files; the rest resumes next Stop from the offsets file",
            file=sys.stderr,
        )
        return 0

    # The append-safe half. Separate loop because these are patched in place, not rewritten.
    values = known_values()
    live_hits = 0
    live_files = 0
    for p in live_targets():
        # Check orphan status between live target files
        if os.getppid() == 1:
            print("secret-scrub: wrapper gone, stopping (LAW 28)", file=sys.stderr)
            return 0

        # Check budget between live target files
        elapsed = time.time() - start_time
        if elapsed >= budget:
            print(
                f"secret-scrub: budget of {budget:.1f}s spent; the rest resumes next Stop",
                file=sys.stderr,
            )
            return 0

        try:
            size = p.stat().st_size
        except OSError:
            continue
        done = offsets.get(str(p), 0)
        start_at = max(0, min(done, size) - OVERLAP) if done else 0
        n = patch_in_place(p, values, check_only, start_at)
        new_offsets[str(p)] = size
        if not n:
            continue
        live_hits += n
        live_files += 1
        rel = str(p).replace(str(HOME), "~")
        print(f"{'FOUND' if check_only else 'scrubbed'} {n} occurrence(s) in {rel}")
    total += live_hits
    touched += live_files

    if check_only:
        print(f"secret-scrub: {total} occurrence(s) in files that should hold none")
        return 1 if total else 0
    save_offsets(new_offsets)
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
    for benign in (
        "a normal sentence",
        "sk-something-short",
        "hf_tooShort",
        "commit 8262a28b0f1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e",
    ):
        got, counts = redact_text(benign)
        check(f"benign kept: {benign[:22]}", (got, counts), (benign, {}))

    # A real file is rewritten in place, line count and mode preserved.
    f = d / "history.jsonl"
    f.write_text(
        json.dumps({"display": "export A=sk-ant-api03-" + "Z" * 40})
        + "\n"
        + json.dumps({"display": "ls -la"})
        + "\n"
    )
    os.chmod(f, 0o600)
    before = f.read_text()
    new, counts = redact_text(before)
    rewrite(f, new)
    after = f.read_text()
    check("rewrite removed the key", "sk-ant-api03" in after, False)
    check("rewrite kept the line count", after.count("\n"), before.count("\n"))
    check("rewrite kept mode 600", oct(f.stat().st_mode & 0o777), "0o600")
    check("rewrite left other lines alone", "ls -la" in after, True)
    check(
        "every line still parses as json",
        all(json.loads(ln) for ln in after.splitlines() if ln.strip()),
        True,
    )

    # The real secret store is never a target.
    names = [p.name for p in targets()]
    check(
        "secrets.sh is never a target",
        any(n.startswith("secrets.sh") for n in names),
        False,
    )

    print("secret-scrub selftest", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    return run(check_only="--check" in sys.argv, full="--full" in sys.argv)


# 2026-08-31: 38 orphaned copies of this script (ppid 1, hours old) took the founder's Mac
# to load average 854. The chain: settings' 30 s hook timeout kills hook-run.py but not this
# child, the orphan keeps scanning gigabytes of transcripts, and every later Stop starts
# another. Three guards close the class. The lock (held inside run(), see _hold_lock) makes
# a second copy exit at once: one scrubber machine-wide, ever. The ppid checks make an orphan
# stop on its own the moment its wrapper is gone. The alarm below is the backstop: an orphan
# dies on its own deadline instead of needing a parent to survive long enough to kill it.
# Exit 0 on all of them, same as the exception door below: a Stop hook must never break the
# session, and the offsets ledger only advances past bytes actually scanned, so whatever a
# cut-short pass missed is the next pass's work.
DEADLINE = float(
    os.environ.get("SECRET_SCRUB_DEADLINE") or (1800 if "--full" in sys.argv else 25)
)


def _deadline(signum: int, frame: object) -> None:
    print(
        f"[secret-scrub] deadline {DEADLINE:g}s hit; the rest is the next pass's work",
        file=sys.stderr,
    )
    sys.exit(0)


if __name__ == "__main__":
    # A Stop hook must never break the session it runs in.
    try:
        signal.signal(signal.SIGALRM, _deadline)
        signal.alarm(int(DEADLINE))
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[secret-scrub] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)
