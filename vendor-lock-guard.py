#!/usr/bin/env python3
"""vendor-lock-guard: no plan step, checkpoint or instruction may require a vendor-only channel.

Founder, 2026-08-26 (crew#182): "why are we using Claude Code RC? that was never in the spec.
The spec is model agnostic, as per our principles." He had already ruled it on 2026-08-25
00:48Z, and session 8f034e1e still told him the next day to "turn on Remote Control for all
sessions" as step 1 of the phone path. LAW 34: provider agnostic from day 0, Claude included.

THE CLASS. A sentence that makes a feature only one vendor ships mandatory for a founder-facing
flow: Anthropic Remote Control, the Claude app, claude.ai, OpenAI Assistants, ChatGPT, Gemini
Live, Copilot Workspace, and so on. Naming the vendor is allowed; a rejection table, a drill and
a comparison all have to name it. What is refused is the vendor name in the same sentence as a
word that makes it required: turn on, enable, must, step N, CPn, done when, the only path.

WHERE IT RUNS.
  Stop hook   reads the last assistant message from the transcript in the hook payload and
              blocks the reply when the text above the --- line commits the founder to a
              vendor-only channel. Same shape as jargon-guard.py.
  --files ... scans markdown, feature and text files (crew specs, rulings, requirements) and
              exits 1 with each offending line. This is the CI/pre-commit face.
  --selftest  proves both ways: the real sentence is refused, the v3 wording is allowed.
Exit 0 clean, 1 offences printed, 2 BLIND (no transcript or unreadable file).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

VENDOR = re.compile(
    r"remote[ -]control|claude\s+app|claude\.ai|anthropic\s+(?:app|console|relay)|"
    r"openai\s+assistants?|chatgpt(?:\s+app)?|gemini\s+live|gemini\s+app|"
    r"copilot\s+workspace|github\s+copilot\s+chat|cursor\s+(?:app|cloud)|"
    r"codex\s+(?:app|cloud)|/config\b",
    re.I,
)
MANDATE = re.compile(
    r"\b(?:turn(?:ed)?\s+on|enable[sd]?|switch(?:ed)?\s+on|activate[sd]?|must|required?|"
    r"mandatory|only\s+(?:path|way|route)|the\s+path\s+is|step\s+\d|cp\s?\d|done\s+when|"
    r"you\s+do\s+one\s+thing|only\s+you\s+can)\b",
    re.I,
)
NEGATED = re.compile(
    r"\b(?:off|not|never|no|withdrawn|withdraw|refused|rejected|struck|cancelled|banned|"
    r"forbidden|cannot|can't|instead\s+of|rather\s+than|why\s+not|versus|vs\.?)\b",
    re.I,
)
FENCE = re.compile(r"```.*?```", re.S)


def above_the_fold(text: str) -> str:
    out = []
    for line in text.splitlines():
        if re.fullmatch(r"\s*-{3,}\s*", line):
            break
        out.append(line)
    return "\n".join(out)


def offences(text: str, whole: bool = False) -> list[tuple[int, str]]:
    """(line number, line) for every line that mandates a vendor-only channel.

    A line that also negates it (off, withdrawn, not a step, instead of) is a ruling, a
    rejection or a comparison, and those have to name the vendor to be readable.
    """
    body = text if whole else above_the_fold(text)
    body = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), body)
    found = []
    for n, line in enumerate(body.splitlines(), 1):
        if VENDOR.search(line) and MANDATE.search(line) and not NEGATED.search(line):
            found.append((n, line.strip()))
    return found


def last_assistant_text(transcript: Path) -> str:
    text = ""
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                text = joined
    return text


def report(found: list[tuple[int, str]], where: str) -> str:
    lines = [f"VENDOR LOCK-IN IN {where}. LAW 34: provider agnostic from day 0, Claude included."]
    for n, line in found:
        lines.append(f"  line {n}: {line[:160]}")
    lines.append("A founder-facing step may not require a channel only one vendor ships. Route it through "
                 "the estate's own front door (the gateway on Telegram, any runtime over ACP) or mark the "
                 "vendor feature as off/withdrawn in the same sentence. Founder, 2026-08-26, crew#182.")
    return "\n".join(lines)


def selftest() -> int:
    real = ("INVENTORY: nothing is broken.\n"
            "Use: in Claude Code run `/config`, turn on \"Remote Control for all sessions\", and turn on "
            "push notifications in the Claude app on your phone. That is step 1 and only you can do it.\n")
    v3 = ("- **Remote Control** — off. Not a fallback, not a step.\n"
          "| Anthropic Remote Control | Claude only; needs claude.ai login; no API key (LAW 34). |\n"
          "**v2 is withdrawn.** It turned on Anthropic Remote Control for one vendor's sessions.\n"
          "Step 1: the phone sends a Telegram message to the gateway; done when the draft comes back.\n")
    below = "All good.\n\n---\n\nTurn on Remote Control in the Claude app.\n"
    checks = [
        ("refuses the real reply", len(offences(real)) == 1),
        ("allows the v3 wording", offences(v3) == []),
        ("below the fold is free in hook mode", offences(below) == []),
        ("but not in file mode", len(offences(below, whole=True)) == 1),
        ("a plain vendor mention is allowed", offences("Claude Code is installed at 0.65.0.") == []),
        ("a mandate without a vendor is allowed", offences("Step 1 must be done first.") == []),
        ("code blocks are not prose", offences("```\nenable remote control\n```\n") == []),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    print(f"vendor-lock-guard selftest: {len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


def scan_files(paths: list[str]) -> int:
    total = 0
    blind = 0
    for p in paths:
        f = Path(p)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            print(f"BLIND {p}: unreadable")
            blind += 1
            continue
        found = offences(text, whole=True)
        for n, line in found:
            print(f"{p}:{n}: {line[:160]}")
        total += len(found)
    print(f"vendor-lock-guard: {total} offending line(s) in {len(paths)} file(s), {blind} unreadable")
    if blind and not total:
        return 2
    return 1 if total else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selftest"]:
        return selftest()
    if argv[:1] == ["--files"]:
        return scan_files(argv[1:])
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("stop_hook_active"):
        return 0
    transcript = Path(payload.get("transcript_path", ""))
    if not transcript.is_file():
        return 0
    text = last_assistant_text(transcript)
    found = offences(text)
    if not found:
        return 0
    # Never block the same text twice, and never more than three times in one session: a Stop
    # hook that always blocks is a wedge, and a wedge gets uninstalled (jargon-guard.py rule).
    state_file = Path.home() / ".claude" / "state" / "vendor-lock-guard.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - missing or corrupt state means no history
        state = {}
    sid = str(payload.get("session_id", ""))
    key = str(hash(text))
    blocked = state.get(sid, [])
    if key in blocked or len(blocked) >= 3:
        return 0
    state[sid] = blocked + [key]
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    print(json.dumps({"decision": "block", "reason": report(found, "A REPLY TO THE FOUNDER")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
