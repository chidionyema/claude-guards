#!/usr/bin/env python3
"""No counted plan on disk, no execution (LAW 51, crew#584; founder 2026-08-29 21:5xZ).

WHY. Founder: "i need to see enforcement on optimised plan, its not negotiable, i see crew
members always taking too long: commit crap code, wait for 40 minutes, build fail, repeat,
fail again and again, break the infra, fix, guard, guard the guard, fix, breaks again, in a
loop all day, and sometimes the problem has already been solved, they just didn't follow laws
to check is there something already existing that handles this."

WHAT EXISTS ALREADY (LAW 3, checked before this file was written): ticket-gate.py binds a
ticket at a session's first mutating call but reads no plan; idp policy/operating_model.rego
`optimised_plan` grades the `Optimised:` line in the PR body, after the loop has already
run. Nothing sits between the two. This does.

WHAT IT REFUSES. A mutating tool call (the same set ticket-gate names: Write, Edit, a Bash
command that writes) from a session that has no plan file at
~/.claude/state/plans/<session>.md carrying these five labelled lines:

  Existing:    what already solves it, with the search that was run (LAW 39, hard rule 3)
  Naive:       the steps and round trips counted before optimising
  Bottleneck:  the one step that costs the most
  Optimised:   `<n> -> <m>, <r> -> <s>; cut: <what, why>` (same shape the rego grades)
  Verify:      the local commands that run green before anything is pushed

Writing or editing the plan file itself is always allowed: that is how a session unblocks.
The founder's own shell is never gated (no session id on stdin). Reads are never gated.

WHAT IT CANNOT SEE (LAW 45 step 5). It grades that a counted plan exists, not that it is
good. A session can write a hollow plan; the PR gate and the founder read the substance.
It does not grade that `Verify:` was run: that is the pre-push hook's job.

Modes: (no args) PreToolUse hook on stdin; --selftest proves the decision table offline.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HOME = Path(os.environ.get("PLAN_GATE_HOME") or Path.home())
PLANS = HOME / ".claude" / "state" / "plans"
LABELS = ("Existing:", "Naive:", "Bottleneck:", "Optimised:", "Verify:")
OPTIMISED = re.compile(
    r"(?m)^Optimised: [^\n]*\d[^\n]*->[^\n]*\d[^\n]*; *cut: \S[^\n]*$"
)


def _ticket_gate():
    spec = importlib.util.spec_from_file_location(
        "ticket_gate", Path(__file__).resolve().parent / "ticket-gate.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def plan_path(sid: str) -> Path:
    return PLANS / f"{sid}.md"


def missing(text: str) -> list[str]:
    """The labelled lines the plan lacks; empty when the plan is counted."""
    gaps = [lab for lab in LABELS if not re.search(rf"(?m)^{re.escape(lab)} *\S", text)]
    if "Optimised:" not in gaps and not OPTIMISED.search(text):
        gaps.append("Optimised: (numbers both sides of -> and a `cut:` clause)")
    return gaps


def touches_plan(tool: str, tool_input: dict, sid: str) -> bool:
    target = str(plan_path(sid))
    if tool in ("Write", "Edit", "MultiEdit"):
        return str(tool_input.get("file_path", "")) == target
    if tool == "Bash":
        return target in str(tool_input.get("command", "")) or "state/plans/" in str(
            tool_input.get("command", "")
        )
    return False


def verdict(tool: str, tool_input: dict, sid: str, needs: bool) -> tuple[int, str]:
    if not sid or not needs or touches_plan(tool, tool_input, sid):
        return 0, ""
    p = plan_path(sid)
    try:
        text = p.read_text()
    except OSError:
        text = ""
    gaps = missing(text)
    if not gaps:
        return 0, ""
    return 2, (
        "BLOCKED by plan-gate: no counted plan for this session (LAW 51, founder 2026-08-29: "
        "'enforcement on optimised plan, its not negotiable').\n"
        f"  plan file   {p}\n"
        f"  missing     {', '.join(gaps)}\n"
        "  instead     write the five lines (Existing: what already solves it and the search you ran; "
        "Naive: steps and round trips counted; Bottleneck:; Optimised: <n> -> <m>, <r> -> <s>; cut: ...; "
        "Verify: the local commands that must be green before push), then run this call again.\n"
        "  procedure   ~/AGENTS-FULL.md, LAW 51"
    )


def hook() -> int:
    tg = _ticket_gate()
    payload = tg._read_payload()
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    sid = payload.get("session_id") or ""
    code, msg = verdict(tool, tool_input, sid, tg._needs_ticket(tool, tool_input))
    if msg:
        print(msg, file=sys.stderr)
    return code


def selftest() -> int:
    good = (
        "Existing: none; searched `grep -rn foo bin`\nNaive: 5 steps, 3 round trips\n"
        "Bottleneck: CI\nOptimised: 5 -> 2, 3 -> 1; cut: the rerun, cached\nVerify: `pytest -q`\n"
    )
    cases = [
        ("read never gated", verdict("Bash", {"command": "ls"}, "s1", False)[0], 0),
        (
            "no session never gated",
            verdict("Write", {"file_path": "/x"}, "", True)[0],
            0,
        ),
        (
            "writing the plan allowed",
            verdict("Write", {"file_path": str(plan_path("s1"))}, "s1", True)[0],
            0,
        ),
        (
            "no plan refused",
            verdict("Write", {"file_path": "/x"}, "s-none", True)[0],
            2,
        ),
        ("counted plan passes", 0 if not missing(good) else 2, 0),
        (
            "uncounted Optimised refused",
            2
            if missing(
                good.replace("5 -> 2, 3 -> 1; cut: the rerun, cached", "made it faster")
            )
            else 0,
            2,
        ),
    ]
    bad = [(n, got, want) for n, got, want in cases if got != want]
    for n, got, want in cases:
        print(f"  {'ok ' if got == want else 'BAD'} {n}: got {got}, want {want}")
    print(json.dumps({"cases": len(cases), "failed": len(bad)}))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else hook())
