"""Founder triage, 2026-08-29 (crew#638): "see these guards are our biggest liabulities". He went
through all 32 session hooks and gave each a verdict. Eight were deleted, and the reason is one
reason: each judged prose or intent -- whether a reply sounded like jargon, whether a session was
idle, whether it was working on its goal -- and there is no ground truth on disk for any of those,
so the guard was guessing and its refusals were noise a session had to work around.

This is the fence for that deletion, and it grades two things a comment cannot:

  1. No deleted guard is back as a file, and no hook slot in the settings file invokes one. The
     failure mode is a session restoring a script from git history to fix a symptom, or a settings
     file drifting back -- both are silent, and both put the refusals back.
  2. Nothing left in the tree imports or executes one. This is the half that catches the real
     defect: a survivor that borrowed a function from a deleted guard raises ImportError at hook
     time, and a hook that crashes is a hook that does not run.

Deliberately NOT graded: the words "goal-guard" or "jargon-guard" appearing in a docstring. Those
are history, and a rule that matched them would be this estate's own recurring mistake -- grading
the text that usually means the thing instead of the thing itself (crew#623)."""
from __future__ import annotations

import ast
import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

DELETED = [
    "goal-guard.py",          # judged whether the session was on its goal
    "feed-guard.py",          # judged whether a handoff said enough
    "context-guard-hook.py",  # judged whether context was being spent well
    "jargon-guard.py",        # judged whether a reply was plain English
    "repeat-guard.py",        # judged whether a turn repeated the last one
    "auto-objective.py",      # judged which board item the session should claim
    "idle-guard.py",          # judged whether a session was idle
    "goal_focus.py",          # goal-guard's state library; nothing else read it
]


def test_no_deleted_guard_is_back_as_a_file() -> None:
    back = [n for n in DELETED if (ROOT / n).exists()]
    assert back == [], (
        "restored from git history: %s. The founder deleted these for judging intent; if one is "
        "needed again the case goes on crew#638, not into the tree." % back
    )


def test_no_surviving_script_imports_or_executes_a_deleted_guard() -> None:
    """Reads every string literal in every live script, so a spec_from_file_location path, a
    subprocess argv and an __import__ name are all caught by the same rule -- the borrow is
    always the filename, whichever of the three shapes it is written in.

    Scoped to the scripts, never the tests. A test carries the name of a deleted guard as data --
    crew#69's fixture is the literal filename that was wrongly committed in 2026-08 -- and a rule
    that refused it would be grading the text instead of the borrow, which is the mistake this
    whole triage exists to stop. A test that really does execute a deleted guard fails by
    executing it; it does not need a string rule to notice."""
    stems = {n[:-3] for n in DELETED} | {n[:-3].replace("-", "_") for n in DELETED}
    offenders: list[str] = []
    for f in sorted(ROOT.glob("*.py")):
        if f.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in DELETED or node.value in stems:
                    offenders.append("%s:%d names %r" % (f.name, node.lineno, node.value))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in stems:
                        offenders.append("%s:%d imports %s" % (f.name, node.lineno, a.name))
            elif isinstance(node, ast.ImportFrom) and (node.module or "") in stems:
                offenders.append("%s:%d imports from %s" % (f.name, node.lineno, node.module))
    assert offenders == [], (
        "a live script still reaches for a deleted guard, so it raises at hook time: %s" % offenders
    )


def test_no_hook_slot_invokes_a_deleted_guard() -> None:
    """The settings file is the founder's machine, not the repository, so this is BLIND rather
    than green when it is not there -- a pass on a file that does not exist would be the silent
    green this whole triage is about."""
    p = pathlib.Path(os.path.expanduser("~/.claude/settings.json"))
    if not p.exists():
        pytest.skip("BLIND: no ~/.claude/settings.json on this machine")
    try:
        settings = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        pytest.fail("~/.claude/settings.json does not parse: %s" % e)
    wired = [
        "%s -> %s" % (event, name)
        for event, groups in (settings.get("hooks") or {}).items()
        for g in groups
        for h in (g.get("hooks") or [])
        for name in DELETED
        if name in (h.get("command") or "")
    ]
    assert wired == [], "a hook slot still invokes a deleted guard: %s" % wired
