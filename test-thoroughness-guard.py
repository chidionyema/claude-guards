#!/usr/bin/env python3
"""Every commit is told, automatically, which of its files have tests that grade nothing.

The founder, 2026-08-21: "too nay bugs", "and having to renid to test thorough", "we need it
auo". The reminder was the founder. That is the defect this closes: a person should not be the
mechanism that makes an agent test its own work.

WHAT IT DOES. PreToolUse on Bash. When the command is a `git commit`, it reads the staged
Python files and, for each one, says whether a test file exists for it and prints the exact
command that PROVES the tests grade it:

    python3 ~/.claude/scripts/edge_test.py --mutate <file> --test "pytest <test> -q"

WHY IT DOES NOT REFUSE. A gate that blocks a commit wedges every session at once, and this
estate has already lost three sessions to a commit hook that held .git/index.lock for 49
minutes. It advises, loudly, with the command ready to paste. Escalating it to a refusal is a
second decision, taken on the measurement this produces, not on the strength of an opinion.

It fails OPEN on every error: a guard that cannot answer must not stop the work.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# `git -C /path commit` is how a commit reaches a worktree, so a regex that only allows bare
# flags misses the common case; and `git log ... # commit audit` merely CONTAINS the word. Walk
# the tokens instead of pattern-matching the line.
_FLAGS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def is_commit(command: str) -> bool:
    """True when this shell line actually runs `git commit`."""
    for segment in re.split(r"[|;&]+|\n", command):
        words = segment.split()
        if "git" not in words:
            continue
        i = words.index("git") + 1
        while i < len(words):
            w = words[i]
            if w in _FLAGS_WITH_VALUE:
                i += 2
                continue
            if w.startswith("-"):
                i += 1
                continue
            return w == "commit"
        continue
    return False


def _staged_py(cwd: str) -> list[str]:
    try:
        p = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                           cwd=cwd, capture_output=True, text=True, timeout=20)
    except (subprocess.SubprocessError, OSError):
        return []
    if p.returncode != 0:
        return []
    return [f for f in p.stdout.split("\n")
            if f.endswith(".py") and "/tests/" not in f and not os.path.basename(f).startswith("test_")]


def _test_for(path: str, cwd: str) -> str | None:
    """The test file that grades this source file, by the estate's own naming."""
    stem = os.path.basename(path)[:-3]
    for cand in (f"tests/unit/test_{stem}.py", f"tests/test_{stem}.py",
                 os.path.join(os.path.dirname(path), f"test_{stem}.py")):
        if os.path.exists(os.path.join(cwd, cand)):
            return cand
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0                                   # fail open: no payload, no opinion
    tool = payload.get("tool_name") or payload.get("tool")
    if tool != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if not is_commit(cmd):
        return 0
    cwd = payload.get("cwd") or os.getcwd()

    files = _staged_py(cwd)
    if not files:
        return 0

    untested, provable = [], []
    for f in files:
        t = _test_for(f, cwd)
        (provable if t else untested).append((f, t))

    lines = ["[test-thoroughness] this commit stages "
             f"{len(files)} python source file(s). A test that has never failed on a mutant "
             "does not grade the code."]
    for f, t in provable:
        lines.append(f'  prove it:  python3 ~/.claude/scripts/edge_test.py --mutate {f} '
                     f'--test "pytest {t} -q"')
    for f, _ in untested:
        lines.append(f"  NO TEST FILE:  {f}  — map the cases: "
                     f"python3 ~/.claude/scripts/edge_test.py --map {f}")
    print("\n".join(lines), file=sys.stderr)
    return 0                                        # advisory, never a refusal


def selftest() -> int:
    fails = []

    def run(payload: dict) -> tuple[int, str]:
        p = subprocess.run([sys.executable, __file__], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stderr

    rc, err = run({"tool_name": "Read", "tool_input": {"file_path": "x"}})
    if rc != 0 or err.strip():
        fails.append("it spoke about a tool that is not Bash")
    rc, err = run({"tool_name": "Bash", "tool_input": {"command": "git status"}})
    if rc != 0 or err.strip():
        fails.append("it spoke about a command that is not a commit")
    rc, _ = run({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"},
                 "cwd": "/nonexistent-path-for-selftest"})
    if rc != 0:
        fails.append(f"it refused when git could not answer (rc={rc}); it must fail open")
    # The regex must see a commit behind git's own global flags, which is how a hook gets past
    # a guard in practice: `git -C /path commit`.
    if not is_commit("git -C /tmp/x commit -m 'y'"):
        fails.append("`git -C <path> commit` was not recognised as a commit")
    if is_commit("git log --format=%s  # commit message audit"):
        fails.append("a command that merely mentions 'commit' was treated as one")
    if not is_commit("git commit -m x"):
        fails.append("a bare `git commit` was not recognised")
    if not is_commit("cd /tmp && git commit -am y"):
        fails.append("a commit after && was not recognised")
    if is_commit("git status"):
        fails.append("`git status` read as a commit")
    if fails:
        print("selftest FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS: silent off-path, fails open, sees `git -C <p> commit`, ignores the word alone.")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    try:
        raise SystemExit(main())
    except Exception:                                # noqa: BLE001 - fail open, always
        raise SystemExit(0)
