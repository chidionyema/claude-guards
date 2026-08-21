#!/usr/bin/env python3
"""Grade an `inventor` answer against the DONE WHEN list in its own role file.

WHY THIS EXISTS. Measured 2026-08-21, on the very first live run of the role. `inventor.md` ends
with four DONE WHEN conditions. The role loaded, produced the right shape, named three distant
fields -- and still failed two of its own four conditions: it killed NO option, and it marked an
option "Proven" with no source. Nothing noticed, because nothing was grading.

Founder, repeatedly: "we shi and dont verify". A DONE WHEN that no machine checks is decoration,
and the role-guard closes that hole for the role FILES while leaving it open for what they PRODUCE.

The four checks below are hardcoded, because they encode meaning a parser cannot recover from
prose. `test_criteria_have_not_drifted` fails if the bullets in inventor.md stop matching them, so
the two cannot silently diverge.

  python3 ~/.claude/scripts/inventor-grade.py < answer.txt
  claude --agent inventor -p "<problem>" | python3 ~/.claude/scripts/inventor-grade.py
  python3 ~/.claude/scripts/inventor-grade.py --selftest
"""
from __future__ import annotations

import pathlib
import re
import sys

ROLE = pathlib.Path.home() / ".claude" / "agents" / "roles" / "inventor.md"

SET_ASIDE = re.compile(r"(?i)obvious[^\n]{0,40}(set aside|forbidden|ruled out|discarded)"
                       r"|(set aside|forbidden|ruled out)[^\n]{0,40}obvious")
FIELD = re.compile(r"(?i)distant field\s*[-:—]{0,2}\s*([a-z][\w /&-]{2,40})")
KILLER = re.compile(r"(?i)killer test")
TIMECOST = re.compile(r"(?i)\b\d+(?:\.\d+)?\s*(?:-|to\s)?\s*\d*\s*"
                      r"(?:h|hr|hrs|hour|hours|d|day|days|w|wk|week|weeks|m|min|minute|minutes)\b")
KILLED = re.compile(r"(?i)\b(killed|kill(?:ed)? this option|ruled out|rejected|abandon(?:ed)?|"
                    r"dead|does not survive|fails the killer test)\b")
FEASIBILITY = re.compile(r"(?i)feasibility\s*[:*]{0,3}\s*\**\s*"
                         r"(proven|plausible|speculative|unknown|untested)")
PROVEN = re.compile(r"(?i)feasibility[^\n]{0,30}proven[^\n]*")
EVIDENCE = re.compile(r"(?i)(https?://|\bused at\b|\bat scale\b|\bmeasured\b|\bcited\b|"
                      r"\b\d{4}\b|\bdocumented\b|\bchromium\b|\bpaper\b|\bstudy\b)")


def grade(text: str) -> list[tuple[bool, str, str]]:
    """Returns (passed, criterion, what was actually found)."""
    out = []

    ok = bool(SET_ASIDE.search(text))
    out.append((ok, "the obvious answer appears, explicitly marked as set aside",
                "found" if ok else "no line marks an obvious answer as set aside"))

    fields = {m.group(1).strip().lower().rstrip(".,;(") for m in FIELD.finditer(text)}
    out.append((len(fields) >= 3, "at least three named distant fields were used",
                f"{len(fields)} named: {', '.join(sorted(fields)) or 'none'}"))

    killers = len(KILLER.findall(text))
    feas = FEASIBILITY.findall(text)
    n_options = max(killers, len(feas))
    out.append((killers >= 1 and killers >= n_options,
                "every option carries a killer test",
                f"{killers} killer tests for {n_options} options"))

    out.append((bool(TIMECOST.search(text)), "the killer tests carry a time cost",
                "found" if TIMECOST.search(text) else "no duration given anywhere"))

    killed = bool(KILLED.search(text))
    out.append((killed, "at least one option has been killed",
                "found" if killed else "no option was killed -- every one survived, which is the "
                                       "tell that the killer tests were not applied"))

    out.append((len(feas) >= 1 and len(feas) >= n_options,
                "a feasibility mark on every option",
                f"{len(feas)} marks for {n_options} options"))

    bad = [m.group(0) for m in PROVEN.finditer(text) if not EVIDENCE.search(m.group(0))]
    out.append((not bad, "no option marked proven without evidence",
                "clean" if not bad else f"{len(bad)} bare 'proven' mark(s): {bad[0][:70]}"))
    return out


def selftest() -> int:
    p = f = 0

    def ck(name, ok):
        nonlocal p, f
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if ok:
            p += 1
        else:
            f += 1

    # The real first run of the role, reduced. It passed the shape and failed two conditions.
    real = """OBVIOUS ANSWER (SET ASIDE): Parallelize tests.
    1. Triage suite. Method: Distant field - logistics. Killer test: compare 4 weeks of CI.
       Time: 1 week passive data + 2h analysis. Feasibility: Proven. Used at scale (Chromium).
    2. Flake detector. Method: Distant field - insurance. Killer test: did any quarantined test
       catch a real failure? Time: 2 weeks data + 1h analysis. Feasibility: Proven. Standard.
    3. Result cache. Method: Distant field - hardware. Killer test: run on a PR touching zero
       tests. Time: 2 hours to build. Feasibility: Plausible, high risk."""
    g = {c: (ok, saw) for ok, c, saw in grade(real)}
    ck("the real run's obvious-answer line is accepted",
       g["the obvious answer appears, explicitly marked as set aside"][0])
    ck("the real run's three distant fields are counted",
       g["at least three named distant fields were used"][0])
    ck("the real run's killer tests are counted", g["every option carries a killer test"][0])
    ck("the real run's time costs are found", g["the killer tests carry a time cost"][0])
    ck("THE REAL RUN IS CAUGHT KILLING NOTHING",
       not g["at least one option has been killed"][0])
    ck("the real run's bare 'Proven. Standard.' is caught as evidence-free",
       not g["no option marked proven without evidence"][0])
    ck("the real run's evidenced 'Proven ... Chromium' is NOT flagged",
       "Standard" in g["no option marked proven without evidence"][1]
       or "Chromium" not in g["no option marked proven without evidence"][1])

    good = real.replace("Feasibility: Plausible, high risk.",
                        "Feasibility: Plausible. KILLED: the dependency graph cannot be trusted.") \
               .replace("Feasibility: Proven. Standard.",
                        "Feasibility: Proven. Measured at 3% flake, 2026.")
    g2 = {c: ok for ok, c, _ in grade(good)}
    ck("a corrected answer passes the kill condition", g2["at least one option has been killed"])
    ck("a corrected answer passes the evidence condition",
       g2["no option marked proven without evidence"])
    ck("a corrected answer passes every condition", all(g2.values()))

    # The THRESHOLD itself, not a count of failures. A mutation changing `>= 3` to `>= 0` passed
    # the whole selftest until these two checks existed, because the count-of-failures check below
    # still cleared its bar with one fewer failure. Grade the boundary, never a proxy for it.
    two = "Distant field - logistics. Distant field - insurance."
    ck("TWO distant fields is not enough: the boundary is graded, not the count of failures",
       not {c: ok for ok, c, _ in grade(two)}["at least three named distant fields were used"])
    three = two + " Distant field - hardware."
    ck("three distant fields clears it",
       {c: ok for ok, c, _ in grade(three)}["at least three named distant fields were used"])
    ck("the same three fields named twice still counts as three, not six",
       "3 named" in {c: saw for ok, c, saw in grade(three + " " + three)}
       ["at least three named distant fields were used"])

    empty = grade("here is an idea: make it faster.")
    ck("an unstructured answer fails most conditions",
       sum(1 for ok, _, _ in empty if not ok) >= 5)

    # Drift: the criteria here must still match the bullets in the role file.
    if ROLE.exists():
        bullets = [b.strip("- ").lower() for b in
                   re.findall(r"^- (.+)$",
                              (re.split(r"^## DONE WHEN\s*$", ROLE.read_text(), flags=re.M)[-1]
                               .split("\n## ")[0]), flags=re.M)]
        joined = " ".join(bullets)
        ck("criteria have not drifted from inventor.md: 'set aside' still required",
           "set aside" in joined)
        ck("criteria have not drifted: 'distant field' still required", "distant field" in joined)
        ck("criteria have not drifted: 'killer test' still required", "killer test" in joined)
        ck("criteria have not drifted: killing an option still required",
           "killed" in joined or "kill" in joined)
        ck("criteria have not drifted: feasibility mark still required", "feasibility" in joined)

    print(f"\n  {p}/{p + f} checks passed")
    return 0 if f == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    text = sys.stdin.read()
    results = grade(text)
    bad = 0
    for ok, crit, saw in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {crit}\n          {saw}")
        bad += not ok
    print(f"\n  {len(results) - bad}/{len(results)} DONE WHEN conditions met")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
