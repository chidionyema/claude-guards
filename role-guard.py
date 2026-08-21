#!/usr/bin/env python3
"""Grades the estate's ROLE files and refuses the ones that are decoration.

Founder, 2026-08-21: "as fiuder i wear too nany hats, i need persons that cover all aspects of
a startup that can nake decisions autononously,strong oownership culture, roles clearly defined
enginerring to narketing to ux, etc", "all roles even ceo", "ultra ultra specialised personas",
"always researching updating knowledhe  being certain", "not guess work".

WHY THE FORMAT IS WHAT IT IS. This is not a style preference, it is three measurements.

  1. A PERSONA LABEL BUYS NOTHING. "When 'A Helpful Assistant' Is Not Really Helpful"
     (Findings of EMNLP 2024, aclanthology.org/2024.findings-emnlp.888/) tested 4 model
     families on 2,410 factual questions with 162 curated roles: adding a persona to the
     system prompt did not improve accuracy, and choosing the best persona per question is no
     better than random. A second angle, different authors and task (JMIR, PMC11467603):
     adding social identities to a role-play prompt dropped misinformation-detection accuracy
     from 68.1% to 29.3%. So a role file that opens with a character sketch is spending its
     tokens on the one thing measured not to work.

  2. WHAT A ROLE ACTUALLY NEEDS is Anthropic's own list, verbatim from
     anthropic.com/engineering/multi-agent-research-system: "an objective, an output format,
     guidance on the tools and sources to use, and clear task boundaries." Those four are
     required sections below, and backstory is not among them.

  3. ROLE FIDELITY IS NOT WHERE AGENTS FAIL. The MAST taxonomy (arxiv.org/abs/2503.13657,
     150 annotated traces across 7 frameworks, inter-annotator kappa 0.88) puts "disobey role
     specification" at 1.5% of failures, against 44.2% for system design and 32.3% for
     inter-agent misalignment. That is why this guard spends most of its checks on BOUNDARIES
     and on overlap between roles, and almost none on character.

WHAT IT REFUSES, and the reason each refusal exists:
  * a role with no ESCALATES section -- an agent that escalates nothing is unbounded, and LAW
    11 says money, business decisions and the irreversible are the founder's alone.
  * a role with no DECIDES ALONE section -- a role that decides nothing is another hat for the
    founder to wear, which is the exact thing he asked us to remove.
  * two roles claiming the same decision -- the 32.3% category. Role AMBIGUITY is the measured
    performance cost in humans too (r=-0.21, Tubre and Collins, Journal of Management 2000);
    role CONFLICT is not (r=-0.07). Overlap is the expensive kind.
  * a character-sketch opening ("You are a seasoned X with N years of experience") -- see 1.
  * a role that claims certainty without an evidence rule -- an LLM asked to state confidence
    is systematically overconfident and its verbalised scores saturate at 0.9/1.0
    (arxiv.org/abs/2306.13063). Certainty has to come from the two-publisher rule in
    decision-log.py, never from asking the model how sure it is.

This guard reads ONLY ~/.claude/agents/roles/*.md. It never grades itself, which is the trap
that a previous guard on this estate fell into: forbidding a literal in a file also forbids it
in the file's own help text.

  python3 ~/.claude/scripts/role-guard.py            # grade every role
  python3 ~/.claude/scripts/role-guard.py --selftest
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROLES_DIR = pathlib.Path.home() / ".claude" / "agents" / "roles"

# The four Anthropic names, plus the three this estate's own laws add.
REQUIRED = (
    "OBJECTIVE",      # Anthropic: an objective
    "OUTPUT",         # Anthropic: an output format
    "SOURCES",        # Anthropic: guidance on the tools and sources to use
    "BOUNDARIES",     # Anthropic: clear task boundaries -- and MAST's 32.3% category
    "DECIDES ALONE",  # the founder's "nake decisions autononously"
    "ESCALATES",      # LAW 11
    "DONE WHEN",      # "we shi and dont verify": done is a command, not an opinion
)

# A character-sketch opening. Deliberately narrow: it matches the "you are a <adjective> <noun>
# with N years" shape and the "seasoned/veteran/world-class expert" shape, not any sentence that
# happens to contain "you are". A broad match here would be a guard grading English rather than
# the defect, which this estate has already paid for four times in one day.
BACKSTORY = re.compile(
    r"(?i)you\s+are\s+an?\s+[\w\s-]{0,40}?"
    r"(?:with\s+\d+\+?\s*years|seasoned|veteran|world[- ]class|legendary|rockstar|10x)"
)

CERTAINTY = re.compile(r"(?i)\b(?:be certain|state your confidence|how confident are you|"
                       r"rate your confidence|confidence score)\b")


def _split(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body). Missing or malformed frontmatter gives ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw, body = text[3:end], text[end + 4:]
    fm = {}
    for line in raw.splitlines():
        if ":" in line and not line.strip().startswith("#"):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, body


def _sections(body: str) -> dict[str, str]:
    """Map SECTION NAME -> its text. A section is a markdown heading in caps."""
    out, cur, buf = {}, None, []
    for line in body.splitlines():
        m = re.match(r"^#{1,6}\s+([A-Z][A-Z \-/]{2,})\s*$", line.strip())
        if m:
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf = m.group(1).strip(), []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf)
    return out


def _decisions(section_text: str) -> set[str]:
    """The decisions a role claims, one per bullet, normalised for comparison."""
    out = set()
    for line in section_text.splitlines():
        s = line.strip()
        if s.startswith(("-", "*")):
            s = re.sub(r"[^a-z0-9 ]", " ", s.lstrip("-* ").lower())
            toks = [t for t in s.split() if len(t) > 3]
            if toks:
                out.add(" ".join(sorted(toks)))
    return out


def grade(roles_dir: pathlib.Path) -> tuple[int, list[str]]:
    problems: list[str] = []
    files = sorted(roles_dir.glob("*.md")) if roles_dir.is_dir() else []
    if not files:
        return 1, [f"no role files in {roles_dir}. A role set with no roles is not a role set."]

    claimed: dict[str, str] = {}   # decision -> the role that claimed it first
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        fm, body = _split(text)
        where = f.name

        for key in ("name", "description"):
            if not fm.get(key):
                problems.append(f"{where}: frontmatter has no `{key}`. Claude Code will not "
                                f"load it as a subagent.")
        if "tools" not in fm:
            problems.append(f"{where}: frontmatter declares no `tools`. A role that inherits "
                            f"every tool has no boundary, and a boundary is the section MAST "
                            f"says actually matters (32.3% of failures).")

        secs = _sections(body)
        for req in REQUIRED:
            if req not in secs:
                problems.append(f"{where}: no `{req}` section.")
            elif not secs[req].strip():
                problems.append(f"{where}: `{req}` is present but empty.")

        if (m := BACKSTORY.search(body)):
            problems.append(
                f"{where}: character-sketch opening {m.group(0)!r}. Measured to buy no accuracy "
                f"(EMNLP 2024, 2410 questions) and to cost it on some tasks (68.1%->29.3%). "
                f"Spend those words on OBJECTIVE and BOUNDARIES instead.")

        if (m := CERTAINTY.search(body)):
            problems.append(
                f"{where}: asks the model to state its own confidence ({m.group(0)!r}). "
                f"Verbalised confidence is systematically overconfident and saturates at "
                f"0.9/1.0. Require two distinct publishers via decision-log.py instead.")

        for d in _decisions(secs.get("DECIDES ALONE", "")):
            if d in claimed and claimed[d] != where:
                problems.append(
                    f"{where}: claims a decision already owned by {claimed[d]}. Two roles "
                    f"owning one decision is role ambiguity, the measured performance cost "
                    f"(r=-0.21), and it is MAST's largest coordination category.")
            else:
                claimed[d] = where

    return (1 if problems else 0), problems


def selftest() -> int:
    import tempfile
    passed = failed = 0

    def ck(name: str, ok: bool) -> None:
        nonlocal passed, failed
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if ok:
            passed += 1
        else:
            failed += 1

    good = """---
name: money
description: owns pricing
tools: Read, Bash
model: sonnet
---

## OBJECTIVE
One sentence.

## DECIDES ALONE
- set the list price of a pack

## ESCALATES
- anything that spends money

## SOURCES
- the ledger

## OUTPUT
- a table

## BOUNDARIES
- does not write code

## DONE WHEN
- `cmd` exits 0
"""
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        ck("an empty roles directory is REFUSED", grade(d)[0] == 1)

        (d / "money.md").write_text(good)
        rc, probs = grade(d)
        ck("a complete role passes", rc == 0 and not probs)

        for missing in ("ESCALATES", "DECIDES ALONE", "BOUNDARIES", "DONE WHEN",
                        "OBJECTIVE", "OUTPUT", "SOURCES"):
            (d / "money.md").write_text(good.replace(f"## {missing}", "## X" + missing))
            rc, probs = grade(d)
            ck(f"a role with no {missing} is REFUSED",
               rc == 1 and any(missing in p for p in probs))
        (d / "money.md").write_text(good)

        (d / "money.md").write_text(good.replace("One sentence.",
                                                 "You are a seasoned CFO who owns the numbers."))
        rc, probs = grade(d)
        ck("a character-sketch opening is REFUSED",
           rc == 1 and any("character-sketch" in p for p in probs))

        (d / "money.md").write_text(good.replace("One sentence.",
                                                 "State your confidence as a number."))
        rc, probs = grade(d)
        ck("asking the model to state its own confidence is REFUSED",
           rc == 1 and any("overconfident" in p for p in probs))

        # The sentence below is NOT a backstory and must not be caught -- a guard that grades
        # English rather than the defect is the failure this estate paid for four times.
        (d / "money.md").write_text(good.replace("One sentence.",
                                                 "You are the single decider for pricing."))
        ck("a plain 'you are the X for Y' sentence is NOT flagged", grade(d)[0] == 0)

        (d / "money.md").write_text(good)
        (d / "growth.md").write_text(good.replace("name: money", "name: growth")
                                         .replace("owns pricing", "owns growth"))
        rc, probs = grade(d)
        ck("two roles claiming the SAME decision is REFUSED",
           rc == 1 and any("already owned by" in p for p in probs))

        (d / "growth.md").write_text(good.replace("name: money", "name: growth")
                                         .replace("owns pricing", "owns growth")
                                         .replace("- set the list price of a pack",
                                                  "- choose which channel to test next"))
        ck("two roles with DIFFERENT decisions both pass", grade(d)[0] == 0)

        (d / "growth.md").write_text(good.replace("name: money", "name: growth")
                                         .replace("owns pricing", "owns growth")
                                         .replace("- set the list price of a pack",
                                                  "- choose which channel to test next")
                                         .replace("tools: Read, Bash\n", ""))
        rc, probs = grade(d)
        ck("a role declaring no tools is REFUSED",
           rc == 1 and any("no `tools`" in p for p in probs))

    print(f"\n  {passed}/{passed + failed} checks passed")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Grade the estate's role files.")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dir", default=str(ROLES_DIR))
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    rc, problems = grade(pathlib.Path(a.dir))
    if not problems:
        n = len(list(pathlib.Path(a.dir).glob("*.md")))
        print(f"role-guard: {n} role files, all complete.")
        return 0
    for p in problems:
        print(f"role-guard: {p}", file=sys.stderr)
    print(f"\nrole-guard: {len(problems)} problems.", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
