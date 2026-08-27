#!/usr/bin/env python3
"""Refuse a reply that claims done without the Definition of Done evidence.

WHY. Founder, 2026-08-25, after a "DONE:" reply that meant "merged, CI green": "what does done
mean" and then "we are upgrading standards now as in tired of repeating myself, i need things
working like clockwork". He handed over AGENTS_md_DoD_v2_1 (Definition of Done, Hard v2.1).
Its Golden Rule: merged code, green CI and passing tests are inventory, not done. Done is the
founder having used the thing end to end and confirmed it.

WHAT IT ENFORCES, mechanically, on the text above the fold of the last assistant message:

  DONE:       needs a `Founder receipt:` line (the founder confirmed it, and where that is
              recorded) AND an `Evidence:` line.
  INVENTORY:  the new word for built-merged-green-awaiting-founder. Needs the five handoff
              items from Gate 4, each as a labelled line: `Built:`, `Use:`, `Expect:`,
              `Not done:`, `Evidence:`.
  Evidence:   must carry something checkable: a URL, a commit hash, a file path, or a
              command in backticks. A bare sentence is not evidence.

WORKING:, WAITING: and BLOCKED: replies are untouched. So is anything below the first `---`.

WHAT IT CANNOT SEE (residual, stated per LAW 45 step 5). It checks the shape of the claim,
not its truth. A false `Founder receipt:` line passes this guard; the founder is the oracle
for that, and the interventions log is where it will be verified once the receipt tooling
exists (crew board, DoD gates issue). It never blocks the same text twice and at most three
times per session, so it cannot wedge a session.

  python3 dod-guard.py --selftest    # one case that must fail, one that must pass
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

STATE = Path.home() / ".claude" / "state" / "dod-guard.json"
MAX_BLOCKS_PER_SESSION = 3

HANDOFF = ("Built:", "Use:", "Expect:", "Not done:", "Evidence:")
CHECKABLE = re.compile(
    r"https?://\S+|\b[0-9a-f]{7,40}\b|`[^`]+`|(?:~|/)[\w./-]+"
)


def above_the_fold(text: str) -> str:
    return text.split("\n---", 1)[0]


def first_word(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    m = re.match(r"\s*\**\s*(DONE|INVENTORY|WORKING|WAITING|BLOCKED|STAGED):", line)
    return m.group(1) if m else ""


def has_line(text: str, label: str) -> bool:
    pat = re.compile(r"^\s*(?:[-*\d.]+\s*)?\**\s*" + re.escape(label), re.IGNORECASE | re.MULTILINE)
    return bool(pat.search(text))


def evidence_is_checkable(text: str) -> bool:
    for line in text.splitlines():
        if re.match(r"^\s*(?:[-*\d.]+\s*)?\**\s*Evidence:", line, re.IGNORECASE):
            rest = line.split(":", 1)[1]
            if CHECKABLE.search(rest):
                return True
    return False


def offences(text: str) -> list[str]:
    fold = above_the_fold(text)
    kind = first_word(fold)
    out: list[str] = []
    if kind == "DONE":
        if not has_line(fold, "Founder receipt:"):
            out.append("DONE: needs a `Founder receipt:` line. If the founder has not used it and "
                       "confirmed it, the word is INVENTORY:, not DONE:.")
        if not has_line(fold, "Evidence:"):
            out.append("DONE: needs an `Evidence:` line.")
    elif kind == "INVENTORY":
        missing = [h for h in HANDOFF if not has_line(fold, h)]
        if missing:
            out.append("INVENTORY: needs all five handoff lines; missing " + ", ".join(f"`{m}`" for m in missing))
    elif kind == "STAGED":
        # crew#281: a staged handoff carries its own default and timer, in the founder's words.
        if not re.search(r"Reply 'go' to execute immediately, 'hold' to review", fold):
            out.append("STAGED: needs the sentence `Reply 'go' to execute immediately, 'hold' to review.`")
        if not re.search(r"Auto-activating in \d+ minutes", fold):
            out.append("STAGED: needs `Auto-activating in <N> minutes.` with a number.")
    if kind in ("DONE", "INVENTORY") and has_line(fold, "Evidence:") and not evidence_is_checkable(fold):
        out.append("`Evidence:` must contain a URL, a commit hash, a file path or a `command`.")
    return out


def last_assistant_text(transcript: Path) -> str:
    text = ""
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
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


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, STATE)


def report(found: list[str]) -> str:
    lines = ["BLOCKED by dod-guard (Definition of Done v2.1, founder 2026-08-25):"]
    lines += [f"  - {f}" for f in found]
    lines.append("  Shape: line 1 DONE:/INVENTORY:/WORKING:/WAITING:/BLOCKED:/STAGED:. INVENTORY carries Built:, Use:, "
                 "Expect:, Not done:, Evidence:. DONE additionally carries Founder receipt:.")
    return "\n".join(lines)


def selftest() -> int:
    bad = "DONE: idp#104 is merged to main as c553b34 and the KINI job has nothing open.\n\nMain CI came back green."
    bad2 = "INVENTORY: the worker restarts on merged code.\nBuilt: restart step.\nEvidence: it works."
    good = ("INVENTORY: the ollama-vision alias is on main; you have not tried it yet.\n"
            "Built: llm/config.yaml now declares `ollama-vision` -> gemma3:4b.\n"
            "Use: `sb ask --vision <image>` from the menu bar.\n"
            "Expect: a caption within 10 seconds.\n"
            "Not done: no founder run yet; pyright has 382 errors.\n"
            "Evidence: https://github.com/chidionyema/idp/pull/104 merged as c553b34.\n")
    good2 = ("DONE: you ran the vision route and confirmed it.\n"
             "Founder receipt: crew#219 comment 5414486390, 'works'.\n"
             "Evidence: https://github.com/chidionyema/idp/pull/104\n")
    working = "WORKING: waiting on CI.\n"
    staged = ("STAGED: platform/access apply (idp#150) is ready. Reply 'go' to execute immediately, 'hold' to "
              "review. Auto-activating in 60 minutes.\n")
    staged_bad = "STAGED: platform/access apply is ready, say go.\n"
    ok = True
    for name, text, expect_block in (("bad", bad, True), ("bad2", bad2, True), ("good", good, False),
                                     ("good2", good2, False), ("working", working, False),
                                     ("staged", staged, False), ("staged_bad", staged_bad, True)):
        got = bool(offences(text))
        print(f"{name}: {'BLOCK' if got else 'PASS'} {'ok' if got == expect_block else 'WRONG'}")
        ok &= got == expect_block
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}
    path = payload.get("transcript_path") or ""
    if not path or not os.path.exists(path):
        return 0
    try:
        text = last_assistant_text(Path(path))
    except OSError:
        return 0
    if not text:
        return 0
    found = offences(text)
    if not found:
        return 0
    session = str(payload.get("session_id") or "unknown")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    state = load_state()
    mine = state.get(session) or {"count": 0, "seen": []}
    if digest in mine["seen"] or mine["count"] >= MAX_BLOCKS_PER_SESSION:
        return 0
    mine["count"] += 1
    mine["seen"] = (mine["seen"] + [digest])[-20:]
    state[session] = mine
    save_state(state)
    print(report(found), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
