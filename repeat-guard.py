#!/usr/bin/env python3
"""Refuse to end a turn that NARRATED the same problem twice without fixing it, and steer.

Founder, 2026-08-21: "also root cause reninder/ never repeat nistake e,g seeing agent narrate a
problen nore than once, trigger a reflection", "this can really tighten behaviour", "and steer".

THE FAILURE IT CATCHES. LAW 6 and the agent tenets both say: investigate, fix, or ticket -- never
narrate. The tell that this is being broken is not one narration, it is the SECOND one: the same
defect described again, in the same session, with nothing changed in between. At that point the
agent is not diagnosing, it is reporting; and the founder pays for the same discovery twice.

WHAT IT MEASURES, and why it is not a proxy. It reads the session transcript, pulls the sentences
that DESCRIBE SOMETHING WRONG out of the assistant's own replies, and matches them by containment
of significant tokens -- the same technique and the same 0.55 threshold that `peer-loop-fence.py`
uses on the estate board, where a real paraphrase of one wedge scored 0.73 and an unrelated finding
0.00. Repeating a problem in DIFFERENT WORDS is still repeating it, so a literal string match would
grade nothing.

THE CONDITION IS NARRATED-TWICE-WITH-NOTHING-DONE, not narrated-twice. A fire being worked is
reported repeatedly on purpose, and that is LAW 1 behaving correctly. So a problem restated AFTER
an Edit, a Write or a NotebookEdit is legal: the world changed between the two mentions. Only a
restatement with no intervening change to anything fires this.

IT BLOCKS ONCE PER PROBLEM. A signature that has already produced a reflection is recorded and
never fires again, so the guard cannot wedge a session the way an unbounded refusal would.

  python3 ~/.claude/scripts/repeat-guard.py           # Stop hook, reads the payload on stdin
  python3 ~/.claude/scripts/repeat-guard.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

CONTAINMENT = 0.55        # peer-loop-fence's measured number, same technique, same estate
STATE_DIR = pathlib.Path.home() / ".claude" / "state" / "repeat-guard"

STOP = {"the", "a", "an", "is", "are", "was", "were", "and", "or", "but", "it", "its", "this",
        "that", "of", "to", "in", "on", "for", "with", "not", "no", "we", "i", "you", "be",
        "has", "have", "had", "so", "at", "by", "from", "as", "which", "what", "there", "then",
        "still", "now", "does", "do", "did", "can", "cannot", "will", "would", "because"}

# A sentence that says something is WRONG. Deliberately narrow: an ordinary statement of fact is
# not a problem narration, and a guard that fires on every sentence teaches nothing.
TROUBLE = re.compile(
    r"(?i)\b(?:is|are|was|were|remains?|stays?)\s+(?:still\s+)?"
    r"(?:broken|failing|stale|missing|down|red|blocked|wrong|dead|empty|orphaned|unmergeable)\b"
    # MEASURED, not chosen. Run against a real 1599-turn transcript, `refuses/refuse` produced
    # 22 of 75 matches and `block/blocks` 7 more -- nearly 40% -- because on this estate those
    # are the ordinary verbs for a guard WORKING ("the fence refuses the repeat"), not for
    # something broken. They are deliberately absent. A false fire on a Stop hook costs the
    # founder a whole turn; a missed case costs nothing but this guard's silence.
    r"|\b(?:fails?|failed|crashe[sd]|throws?|errors? out|times? out|hangs?|wedges?|"
    r"cannot be|does not (?:exist|work|run|fire|load)|never (?:fires?|runs?|loads?))\b"
    r"|\bno (?:such file|git|commit|proof|test|guard|owner)\b")

# The guard's own words, and quoted evidence, must never count as the agent narrating.
def strip_noise(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)      # fenced code and pasted output
    text = re.sub(r"`[^`]*`", " ", text)                    # inline code, paths, commands
    text = re.sub(r"^\s*>.*$", " ", text, flags=re.M)       # quoted material
    text = re.sub(r"(?i)\[repeat-guard\].*", " ", text)     # anything this guard injected
    return text


def tokens(sentence: str) -> set[str]:
    words = re.findall(r"[a-z0-9_.-]{3,}", sentence.lower())
    return {w for w in words if w not in STOP}


def containment(a: set[str], b: set[str]) -> float:
    """Shared tokens over the SMALLER set, so a terse restatement still matches its original."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def problems(text: str) -> list[str]:
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", strip_noise(text)):
        s = sentence.strip()
        if 20 <= len(s) <= 400 and TROUBLE.search(s) and len(tokens(s)) >= 4:
            out.append(s)
    return out


def read_turns(transcript: pathlib.Path) -> list[dict]:
    """One entry per assistant reply: its text, and whether it changed anything."""
    turns = []
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if row.get("type") != "assistant":
                continue
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            text, changed = [], False
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text.append(block.get("text") or "")
                elif block.get("type") == "tool_use":
                    if block.get("name") in ("Edit", "Write", "NotebookEdit"):
                        changed = True
                    elif block.get("name") == "Bash":
                        cmd = str((block.get("input") or {}).get("command", ""))
                        if re.search(r"(?:^|[|;&\s])(?:cat|tee)\s*>|>>|\bmv\b|\bsed -i\b|"
                                     r"\bpython3? - <<|\bcp\b|\bchmod\b|\btouch\b", cmd):
                            changed = True
            turns.append({"text": "\n".join(text), "changed": changed})
    return turns


def find_repeat(turns: list[dict], already: list[list[str]]) -> tuple[str, str] | None:
    """The first problem narrated in a LATER turn with no change made since the earlier one."""
    seen: list[tuple[int, str, set[str]]] = []
    done = [set(t) for t in already]
    for i, turn in enumerate(turns):
        for p in problems(turn["text"]):
            tk = tokens(p)
            if any(containment(tk, d) >= CONTAINMENT for d in done):
                continue                                   # already reflected on: never twice
            for j, earlier, etk in seen:
                if containment(tk, etk) < CONTAINMENT:
                    continue
                if any(t["changed"] for t in turns[j:i]):
                    continue                               # something was DONE in between: legal
                return earlier, p
            seen.append((i, p, tk))
    return None


def reflection(first: str, again: str) -> str:
    return (
        "[repeat-guard] YOU HAVE NARRATED THE SAME PROBLEM TWICE AND CHANGED NOTHING IN BETWEEN.\n\n"
        f"  first time:  {first[:200]}\n"
        f"  again now:   {again[:200]}\n\n"
        "Founder rule: investigate, fix, or ticket. Never narrate. The second description is the\n"
        "tell -- the first one was diagnosis, this one is a report, and the founder is paying for\n"
        "the same discovery twice.\n\n"
        "DO ONE OF THESE THREE NOW, then end the turn:\n"
        "  1. FIX IT. If the command, the credential and the permission are on this machine, it is\n"
        "     yours (LAW 5). Make the change, then say what you changed.\n"
        "  2. TICKET IT with a number. A GitHub issue or a row in the register, linked, so the next\n"
        "     session starts from your standing point instead of the beginning (LAW 16).\n"
        "  3. NAME WHAT MECHANICALLY BLOCKS YOU. Not 'this is hard' -- the exact permission the\n"
        "     classifier refuses, the credential that is nowhere on this machine, or the decision\n"
        "     only the founder can make. If you cannot name it, you are not blocked (LAW 5).\n\n"
        "Then close the CLASS, not the instance (LAW 6): can the system heal itself, can a machine\n"
        "refuse the mistake, and only if neither -- a memory file. This guard blocks once for this\n"
        "problem, so the next Stop goes through either way."
    )


def selftest() -> int:
    p = f = 0

    def ck(name, ok):
        nonlocal p, f
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if ok:
            p += 1
        else:
            f += 1

    A = "The session-start hook is still failing on every start and nobody has looked at it."
    B = "That session-start hook fails on every start, which nobody has looked at."
    C = "The golden set has been saturated at 1.00 for weeks so it cannot register a regression."

    ck("a problem sentence is recognised", problems(A) == [A])
    ck("an ordinary sentence is not a problem", problems("I built the model and it is measured.") == [])
    ck("a paraphrase scores above the threshold, so different words are still a repeat",
       containment(tokens(A), tokens(B)) >= CONTAINMENT)
    ck("an unrelated problem scores below it", containment(tokens(A), tokens(C)) < CONTAINMENT)

    ck("narrated once does not fire", find_repeat([{"text": A, "changed": False}], []) is None)
    ck("NARRATED TWICE WITH NOTHING DONE FIRES",
       find_repeat([{"text": A, "changed": False}, {"text": B, "changed": False}], []) is not None)
    ck("narrated twice WITH a change in between is legal: a fire being worked is reported",
       find_repeat([{"text": A, "changed": True}, {"text": B, "changed": False}], []) is None)
    ck("a change in a LATER turn does not excuse an earlier repeat",
       find_repeat([{"text": A, "changed": False}, {"text": B, "changed": True}], []) is not None)
    ck("two DIFFERENT problems do not fire",
       find_repeat([{"text": A, "changed": False}, {"text": C, "changed": False}], []) is None)
    ck("a problem already reflected on never fires again",
       find_repeat([{"text": A, "changed": False}, {"text": B, "changed": False}],
                   [sorted(tokens(A))]) is None)
    ck("the guard's own injected text is not counted as the agent narrating",
       problems("[repeat-guard] the hook is still failing on every start and nobody looked") == [])
    ck("a quoted error block is not counted as the agent narrating",
       problems("Here is the output:\n```\nthe build fails on every commit and is still red\n```") == [])
    ck("an inline-code path is not counted", problems("`scripts/x.py is broken and fails always`") == [])
    ck("a sentence too short to be a real claim is ignored", problems("it fails.") == [])
    ck("A GUARD DOING ITS JOB IS NOT A PROBLEM: 'refuses' and 'blocks' are this estate's normal "
       "verbs for working code, and cost 29 of 75 matches on a real transcript",
       problems("The peer-loop fence refuses the repeat and blocks the duplicate send.") == [])
    ck("but a real breakage in the same sentence shape still counts",
       problems("The peer-loop fence never fires and the duplicate send goes through.") != [])

    turns = read_turns(pathlib.Path("/nonexistent-transcript.jsonl")) if False else None
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        t = pathlib.Path(td) / "t.jsonl"
        t.write_text("\n".join([
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": A}]}}),
            "not json at all",
            json.dumps({"type": "user", "message": {"content": "ignore me"}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": B}]}}),
        ]) + "\n")
        turns = read_turns(t)
        ck("a malformed transcript line is skipped rather than crashing the hook", len(turns) == 3)
        ck("an Edit tool call marks the turn as having changed something", turns[1]["changed"])
        ck("a real transcript with an Edit between two narrations does not fire",
           find_repeat(turns, []) is None)
        t.write_text("\n".join([
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": A}]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Grep", "input": {}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": B}]}}),
        ]) + "\n")
        ck("READ-ONLY tool calls between two narrations do NOT excuse the repeat",
           find_repeat(read_turns(t), []) is not None)

    r = reflection(A, B)
    ck("the reflection STEERS: it names the three legal moves",
       "FIX IT" in r and "TICKET IT" in r and "MECHANICALLY BLOCKS" in r)
    ck("the reflection quotes both narrations back", A[:40] in r and B[:40] in r)

    print(f"\n  {p}/{p + f} checks passed")
    return 0 if f == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, TypeError):
        return 0
    if payload.get("stop_hook_active"):
        return 0
    path = payload.get("transcript_path") or ""
    if not path or not pathlib.Path(path).exists():
        return 0
    session = payload.get("session_id") or "nosession"
    state = STATE_DIR / f"{session}.json"
    try:
        already = json.loads(state.read_text(encoding="utf-8")) if state.exists() else []
    except (ValueError, OSError):
        already = []
    try:
        turns = read_turns(pathlib.Path(path))
    except OSError:
        return 0
    hit = find_repeat(turns, already)
    if not hit:
        return 0
    first, again = hit
    already.append(sorted(tokens(again)))
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(already[-50:]), encoding="utf-8")
    except OSError:
        try: (__import__("sys").path.append(__import__("os").path.expanduser("~/.claude/scripts")), __import__("guard_report").broken(__file__, 275))
        except Exception: pass
    print(reflection(first, again), file=sys.stderr)
    return 2      # block the Stop; the text above reaches the model


if __name__ == "__main__":
    sys.exit(main())
