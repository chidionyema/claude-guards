#!/usr/bin/env python3
"""Differential replay: does policy/command.rego decide what rule-guard.py decides?

WHY THIS IS A TEST AND NOT A SCRIPT
-----------------------------------
~/AGENTS.md, "How to test", rung 3: for any rewrite, the oracle is the current
implementation. Run both over the recorded corpus and diff. One assertion,
thousands of cases.

rule-guard.py is a live PreToolUse hook. Every session on this machine sends it
every Bash command before running it, so a rewrite that refuses one command the
Python permitted stops work across the estate, and one that permits a command
the Python refused reopens an incident that has already been paid for. Neither
failure is visible by reading the two side by side: the difference between
Python's `re` and Go's RE2 is exactly the kind of thing that looks identical and
is not. Two of these eleven patterns used negative lookahead, which RE2 cannot
compile, and had to be rewritten. This is what proves the rewrites.

The corpus is not invented. It is every Bash command this estate has actually
run, read out of the session transcripts, which is the "the users already wrote
these" property that makes rung 3 cheap.

THIS FILE IS TEMPORARY, BY THE SAME RULE
----------------------------------------
"A differential test is a migration tool, not a permanent test: delete it when
the old implementation goes." It exists to move eleven refusals off Python. When
rule-guard.py no longer holds them, the oracle is gone and so is this file. It
is counted as added Python in the PR that lands it and as deleted Python in the
PR that finishes the migration; the net across the two is negative, which is
what crew#126 AC6 asks for.

    python3 policy/differential.py            # replay the transcript corpus
    python3 policy/differential.py --self     # examples only, no transcripts
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGO = HERE / "command.rego"

#: The rules that moved. Named explicitly rather than diffed wholesale, because
#: rule-guard.py keeps four refusals that ask git and gh questions Rego cannot
#: ask (rule_two_dot_diff, rule_pr_size, rule_merge_red_pr,
#: rule_commit_in_shared_checkout) plus rule_secret_store_dump, which rewrites
#: the command before matching. A disagreement on any of those is expected and
#: is not a migration defect, so they are excluded here rather than explained
#: away in the output.
MOVED = (
    "rule_add_all",
    "rule_no_verify",
    "rule_index_lock",
    "rule_ci_autoscale",
    "rule_clone_makes_a_standby",
    "rule_shared_stash",
    "rule_force_push",
    "rule_direct_push_main",
    "rule_no_fly_revival",
)


def load_python_rules(guard: Path):
    """The live rule functions, imported from the hook itself.

    Imported rather than copied: a copy is a second implementation, and then the
    diff proves the copy agrees with the copy.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("rule_guard_live", guard)
    if spec is None or spec.loader is None:
        sys.exit(f"cannot import {guard}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    by_name = {f.__name__: f for f in getattr(mod, "RULES", ())}
    missing = [n for n in MOVED if n not in by_name]
    if missing:
        sys.exit(
            "these rules are not in rule-guard.py's RULES tuple, so the oracle "
            f"cannot be consulted for them: {', '.join(missing)}"
        )
    return [by_name[n] for n in MOVED]


def python_verdict(rules, cmd: str) -> bool:
    """True when any migrated Python rule refuses this command."""
    for fn in rules:
        try:
            if fn(cmd) is not None:
                return True
        except Exception:
            # A rule that raises is not a refusal. rule-guard.py's own dispatch
            # decides what to do with that; here it only matters that it did
            # not refuse, so the comparison stays honest.
            continue
    return False


def opa_verdicts(cmds: list[str]) -> list[bool]:
    """True per command when the Rego policy refuses it.

    One `opa eval` for the whole corpus rather than one per command: process
    start is 40ms and the corpus is thousands of lines.

    --strict-builtin-errors is not optional. Without it an uncompilable regex
    makes regex.match undefined and every rule using it silently permits
    everything, which would make this whole comparison report agreement while
    the policy refuses nothing.
    """
    doc = {"cases": [{"i": i, "command": c} for i, c in enumerate(cmds)]}
    driver = """
package differential
import rego.v1
import data.command
refused contains c.i if {
  some c in input.cases
  count(command.deny) > 0 with input as {"command": c.command}
}
"""
    drv = HERE / ".differential_driver.rego"
    drv.write_text(driver, encoding="utf-8")
    try:
        out = subprocess.run(
            [
                "opa", "eval", "--strict-builtin-errors", "--format", "json",
                "-d", str(REGO), "-d", str(drv), "--stdin-input",
                "data.differential.refused",
            ],
            input=json.dumps(doc),
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        drv.unlink(missing_ok=True)
    if out.returncode != 0:
        sys.exit(f"opa failed:\n{out.stdout}\n{out.stderr}")
    parsed = json.loads(out.stdout)
    try:
        refused = set(parsed["result"][0]["expressions"][0]["value"])
    except (KeyError, IndexError):
        refused = set()
    return [i in refused for i in range(len(cmds))]


def check_not_broken() -> list[str]:
    """The policy's opinion of itself, before any comparison is trusted."""
    out = subprocess.run(
        ["opa", "eval", "--strict-builtin-errors", "--format", "json",
         "-d", str(REGO), "data.command.broken"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        sys.exit(f"opa could not evaluate the policy at all:\n{out.stderr}")
    parsed = json.loads(out.stdout)
    try:
        return list(parsed["result"][0]["expressions"][0]["value"])
    except (KeyError, IndexError):
        return []


def transcript_corpus(limit_files: int = 400) -> list[str]:
    """Every Bash command in the session transcripts on this machine.

    Deduplicated, because the same command run five hundred times is one case.
    Bounded by file count because the transcript tree is large and this is a
    test, not a survey.
    """
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return []
    seen: set[str] = set()
    files = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[:limit_files]:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"Bash"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    for block in _content_blocks(rec):
                        if block.get("name") != "Bash":
                            continue
                        cmd = (block.get("input") or {}).get("command")
                        if isinstance(cmd, str) and cmd.strip():
                            seen.add(cmd)
        except OSError:
            continue
    return sorted(seen)


def _content_blocks(rec: dict):
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict)]


def main() -> int:
    guard = Path(
        os.environ.get("RULE_GUARD", Path.home() / ".claude" / "scripts" / "rule-guard.py")
    )
    if not guard.is_file():
        sys.exit(f"no oracle to compare against: {guard} does not exist")

    broken = check_not_broken()
    if broken:
        print("POLICY IS BROKEN -- not comparing anything until this is fixed:")
        for b in broken:
            print(f"  - {b}")
        return 1
    print("policy self-check: every rule agrees with its own examples")

    rules = load_python_rules(guard)

    cases: list[str] = []
    # The examples first, so the run says something even where there are no
    # transcripts -- a fresh clone, a CI runner.
    doc = json.loads(
        subprocess.run(
            ["opa", "eval", "--format", "json", "-d", str(REGO), "data.command.rules"],
            capture_output=True, text=True, check=True,
        ).stdout
    )
    for r in doc["result"][0]["expressions"][0]["value"]:
        cases.append(r["must_match"])
        cases.append(r["must_not_match"])
        cases.append(f"{r['must_match']}  # {r['marker']}")
    n_examples = len(cases)

    if "--self" not in sys.argv:
        corpus = transcript_corpus()
        cases.extend(c for c in corpus if c not in set(cases))
        print(f"corpus: {n_examples} policy examples + {len(cases) - n_examples} distinct "
              f"commands replayed from this machine's transcripts")
    else:
        print(f"corpus: {n_examples} policy examples (--self, transcripts skipped)")

    theirs = [python_verdict(rules, c) for c in cases]
    ours = opa_verdicts(cases)

    disagree = [(c, p, o) for c, p, o in zip(cases, theirs, ours) if p != o]
    refused = sum(1 for x in theirs if x)
    print(f"replayed {len(cases)} commands; the Python oracle refuses {refused} of them")

    if not disagree:
        print(f"AGREE on all {len(cases)}. The Rego decides what the Python decides.")
        return 0

    print(f"\nDISAGREE on {len(disagree)} of {len(cases)}:")
    for cmd, p, o in disagree[:40]:
        one = cmd.replace("\n", "\\n")[:150]
        print(f"  python={'REFUSE' if p else 'permit':7} rego={'REFUSE' if o else 'permit':7}  {one}")
    if len(disagree) > 40:
        print(f"  ... and {len(disagree) - 40} more")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
