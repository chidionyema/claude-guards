#!/usr/bin/env python3
"""Edge-case testing, automated: prove a test grades the code, and map the cases before writing.

The founder, 2026-08-21: "we need autonation of edge cae testing", "to hekp u nove faster".

Two things were being done by hand on this estate, every time, and both are mechanical:

1. MUTATION-PROVING. Writing a test proves nothing until you break the code and watch the test
   fail. That has been a manual edit-run-revert loop, and an interrupted one LEAVES THE
   MUTATION BEHIND -- the restore is the last step, so a tool timeout commits a deliberate bug
   (memory: an-interrupted-mutation-loop-leaves-the-mutation). This does it in a loop that
   cannot leave one: the original is written to a sibling `.mutation-backup` BEFORE the first
   edit, restored by atexit and by SIGINT/SIGTERM, and restored on the NEXT run if a crash beat
   all three. A surviving mutant is a test that does not grade.

2. THE EDGE-CASE MAP. LAW 4 says name the empty case, the one case, the many case, the
   already-running case, the two-agents case and the half-succeeded case BEFORE the first edit.
   `--map` reads the file and asks those questions against what the code actually does -- it
   loops, it writes files, it shells out, it takes a list -- so the questions are about this
   function rather than a generic checklist.

    python3 edge_test.py --map prospector/verify.py
    python3 edge_test.py --mutate scripts/ci_capacity.py --test "pytest tests/unit/test_ci_capacity.py -q"
    python3 edge_test.py --selftest
"""
from __future__ import annotations

import argparse
import ast
import atexit
import os
import re
import shutil
import signal
import subprocess
import sys

BACKUP_SUFFIX = ".mutation-backup"

# Each mutation is (name, pattern, replacement). They are deliberately small and syntactic: a
# mutant that does not parse teaches nothing, and one that changes behaviour in an obvious way
# is exactly what a real test should catch.
MUTATIONS: list[tuple[str, str, str]] = [
    ("== becomes !=", r"(?<![!<>=])== ", "!= "),
    ("!= becomes ==", r"!= ", "== "),
    (">= becomes >", r">= ", "> "),
    ("<= becomes <", r"<= ", "< "),
    ("> becomes >=", r"(?<![-<>=])> ", ">= "),
    ("and becomes or", r"\band\b", "or"),
    ("or becomes and", r"\bor\b", "and"),
    ("not is dropped", r"\bnot ", ""),
    ("True becomes False", r"\bTrue\b", "False"),
    ("False becomes True", r"\bFalse\b", "True"),
    ("+ 1 becomes + 0", r"\+ 1\b", "+ 0"),
    ("continue becomes pass", r"\bcontinue\b", "pass"),
]


def _first_diff(a: str, b: str) -> int:
    """Index of the first character where two strings differ; len(a) when one is a prefix."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def _restore(path: str) -> bool:
    """Put the original back. Safe to call any number of times, from any of three routes."""
    backup = path + BACKUP_SUFFIX
    if os.path.exists(backup):
        shutil.move(backup, path)
        return True
    return False


def _run(cmd: str, cwd: str, timeout: int) -> int:
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, timeout=timeout,
                           capture_output=True, text=True)
        return p.returncode
    except subprocess.TimeoutExpired:
        return 124


def mutate(path: str, test_cmd: str, cwd: str = ".", timeout: int = 900,
           limit: int = 12) -> int:
    """Apply each mutation in turn and report which ones the tests do not catch."""
    path = os.path.abspath(path)
    # A crash on a PREVIOUS run beats atexit and both signals. Restoring first means the
    # deliberate bug lives at most until the next invocation, never until the next commit.
    if _restore(path):
        print(f"restored a mutation left behind by an earlier run: {path}")

    original = open(path).read()
    shutil.copy2(path, path + BACKUP_SUFFIX)
    atexit.register(_restore, path)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_a: (_restore(path), sys.exit(130)))

    print(f"baseline: {test_cmd}")
    base = _run(test_cmd, cwd, timeout)
    if base != 0:
        _restore(path)
        print(f"BASELINE IS RED (exit {base}). A mutation run against red tests proves nothing.",
              file=sys.stderr)
        return 2

    applied, survivors = 0, []
    for name, pat, rep in MUTATIONS:
        if applied >= limit:
            break
        mutated, n = re.subn(pat, rep, original, count=1)
        if not n or mutated == original:
            continue
        try:
            ast.parse(mutated)
        except SyntaxError:
            continue                       # a mutant that will not parse grades nothing
        # A survivor is only actionable if you know WHERE it survived. Without the line, the
        # report says "your tests do not grade `and`" about a file with ninety of them.
        line_no = original[:_first_diff(original, mutated)].count("\n") + 1
        snippet = mutated.split("\n")[line_no - 1].strip()[:70]
        open(path, "w").write(mutated)
        applied += 1
        rc = _run(test_cmd, cwd, timeout)
        status = "caught" if rc != 0 else "SURVIVED"
        print(f"  {status:>8}  {name}  line {line_no}: {snippet}")
        if rc == 0:
            survivors.append(f"{name} at line {line_no}: {snippet}")
    _restore(path)

    print(f"\n{applied} mutations applied, {len(survivors)} survived.")
    if survivors:
        print("A surviving mutant is code the tests do not grade:")
        for s in survivors:
            print("  -", s)
        return 1
    print("Every mutation was caught. The tests grade this file.")
    return 0


def _questions(fn: ast.FunctionDef, src: str) -> list[str]:
    """LAW 4's questions, asked against what THIS function actually does."""
    body = ast.dump(fn)
    seg = ast.get_source_segment(src, fn) or ""
    qs: list[str] = []
    args = [a.arg for a in fn.args.args if a.arg not in ("self", "cls")]
    if args:
        qs.append(f"empty / one / many: what does it do when {args[0]} is empty, has one "
                  f"element, has thousands?")
    if "For(" in body or "While(" in body or "comprehension" in body:
        qs.append("the loop: what if it runs zero times? what if it never ends?")
    if "Call(func=Attribute(value=Name(id='os'" in body or "open(" in seg:
        qs.append("half-succeeded: what is on disk if this dies between the write and the "
                  "rename? is the write atomic?")
    if "subprocess" in seg or "Popen" in seg:
        qs.append("the child: what if it hangs, exits 127, or writes 200MB to stdout? is there "
                  "a timeout, and is its exit status read before any pipe?")
    if any(w in seg for w in ("lock", "Lock", "flock", "lease", "claim")):
        qs.append("two agents: what happens when this runs twice at once? who holds the lock "
                  "when the holder dies?")
    if any(w in seg for w in ("json.load", "loads(", "parse", "re.")):
        qs.append("malformed input: what does it do with truncated, empty or hostile input?")
    if "return" in seg and ("None" in seg or "except" in seg):
        qs.append("the silent miss: does any branch return early with nothing? a bare return on "
                  "an unknown branch is how 10 criticals were dropped in 18 hours here.")
    if not qs:
        qs.append("empty / one / many, already-running, half-succeeded — none of the shapes "
                  "this tool detects are present, so ask them by hand.")
    return qs


def edge_map(path: str) -> int:
    src = open(path).read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"{path} will not parse: {e}", file=sys.stderr)
        return 1
    fns = [n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not fns:
        print(f"{path}: no functions")
        return 0
    print(f"{path}: {len(fns)} functions\n")
    for fn in fns:
        print(f"{fn.name}  (line {fn.lineno})")
        for q in _questions(fn, src):
            print("   -", q)
        print()
    return 0


def selftest() -> int:
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory() as d:
        mod = os.path.join(d, "m.py")
        open(mod, "w").write("def over(n):\n    return n >= 10\n")
        # A test that actually grades the boundary.
        good = os.path.join(d, "t_good.py")
        open(good, "w").write("import m\nassert m.over(10) and not m.over(9)\n")
        rc = mutate(mod, f"{sys.executable} t_good.py", cwd=d, timeout=60)
        if rc != 0:
            fails.append(f"a grading test reported survivors (rc={rc})")
        if os.path.exists(mod + BACKUP_SUFFIX):
            fails.append("a backup file was left behind")
        if open(mod).read() != "def over(n):\n    return n >= 10\n":
            fails.append("the file was not restored")

        # A test that does not grade the boundary: >= to > must survive.
        weak = os.path.join(d, "t_weak.py")
        open(weak, "w").write("import m\nassert m.over(100)\n")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = mutate(mod, f"{sys.executable} t_weak.py", cwd=d, timeout=60)
        if rc != 1:
            fails.append(f"a non-grading test was not caught (rc={rc}, wanted 1)")
        if "line 2" not in buf.getvalue():
            fails.append("a survivor was reported without the line it survived on")

        # The trap this tool exists to close: a mutation left behind by a crash is restored
        # on the NEXT run, before anything else happens.
        open(mod, "w").write("def over(n):\n    return n > 10\n")          # the mutant
        shutil.copy2(os.path.join(d, "m.py"), mod + BACKUP_SUFFIX)
        open(mod + BACKUP_SUFFIX, "w").write("def over(n):\n    return n >= 10\n")
        mutate(mod, f"{sys.executable} t_good.py", cwd=d, timeout=60)
        if "n >= 10" not in open(mod).read():
            fails.append("a mutation left by a crashed run was not restored")

        rc = edge_map(mod)
        if rc != 0:
            fails.append("--map failed on a valid file")
    if fails:
        print("selftest FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS: catches a non-grading test, restores after a crash, maps a file.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", metavar="FILE")
    ap.add_argument("--mutate", metavar="FILE")
    ap.add_argument("--test", metavar="CMD", help="the command that must FAIL on a mutant")
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.map:
        return edge_map(a.map)
    if a.mutate:
        if not a.test:
            ap.error("--mutate needs --test: a mutation is only proof if a command grades it")
        return mutate(a.mutate, a.test, a.cwd, a.timeout, a.limit)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
