#!/usr/bin/env python3
"""Refuse a reply that claims done without the Definition of Done evidence.

WHY. Founder, 2026-08-25, after a "DONE:" reply that meant "merged, CI green": "what does done
mean" and then "we are upgrading standards now as in tired of repeating myself, i need things
working like clockwork". He handed over AGENTS_md_DoD_v2_1 (Definition of Done, Hard v2.1).
Its Golden Rule: merged code, green CI and passing tests are inventory, not done. Done is the
founder having used the thing end to end and confirmed it.

WHAT IT ENFORCES is in policy/dod.rego now, not here -- see that file's header for why. This
file is the adapter: it reads the transcript, cuts the last assistant message at the first `---`
line (above_the_fold), reads its first word (first_word), and asks `data.dod.deny` about the
rest. What Rego cannot do is the other half of this file: read the transcript off disk, and
remember -- across invocations, which Rego has no state for -- that it never blocks the same
text twice and at most three times per session, so it cannot wedge a session.

FAILS OPEN on a missing or broken `opa`, same doctrine as blocker-guard.py (its own sibling
adapter, migrated the same way on crew#281): a guard that blocks on its own blindness stops
every DONE:/INVENTORY: reply the moment the binary moves. rule-guard.py and opa-hook.py fail
CLOSED because they gate tool permissions, a different risk; this one gates prose.

    python3 dod-guard.py --selftest    # the eleven cases policy/dod_test.rego also proves
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / ".claude" / "state" / "dod-guard.json"
MAX_BLOCKS_PER_SESSION = 3
POLICY = Path(__file__).resolve().parent / "policy"


def above_the_fold(text: str) -> str:
    return text.split("\n---", 1)[0]


def first_word(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    m = re.match(r"\s*\**\s*(DONE|INVENTORY|WORKING|WAITING|BLOCKED|STAGED):", line)
    return m.group(1) if m else ""


def offences(text: str) -> list[str]:
    """Ask policy/dod.rego about the reply. [] on any opa failure -- BLIND permits, per the
    module docstring's fail-open doctrine."""
    fold = above_the_fold(text)
    opa = shutil.which("opa")
    if not opa:
        return []
    try:
        out = subprocess.run(  # noqa: S603  argv list, no shell, our own paths
            [
                opa,
                "eval",
                "--format",
                "json",
                "--ignore",
                "fixtures",
                "--ignore",
                "*.json",
                "--data",
                str(POLICY),
                "--stdin-input",
                "data.dod.deny",
            ],
            input=json.dumps({"reply": fold, "kind": first_word(fold)}),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    try:
        return sorted(json.loads(out.stdout)["result"][0]["expressions"][0]["value"])
    except (ValueError, KeyError, IndexError, TypeError):
        return []


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
            parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
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
    lines.append(
        "  Shape: line 1 DONE:/INVENTORY:/WORKING:/WAITING:/BLOCKED:/STAGED:. INVENTORY carries Built:, Use:, "
        "Expect:, Not done:, Evidence:. DONE additionally carries Founder receipt:."
    )
    return "\n".join(lines)


def selftest() -> int:
    bad = "DONE: idp#104 is merged to main as c553b34 and the KINI job has nothing open.\n\nMain CI came back green."
    bad2 = "INVENTORY: the worker restarts on merged code.\nBuilt: restart step.\nEvidence: it works."
    good = (
        "INVENTORY: the ollama-vision alias is on main; you have not tried it yet.\n"
        "Built: llm/config.yaml now declares `ollama-vision` -> gemma3:4b.\n"
        "Use: `sb ask --vision <image>` from the menu bar.\n"
        "Expect: a caption within 10 seconds.\n"
        "Not done: no founder run yet; pyright has 382 errors.\n"
        "Evidence: https://github.com/chidionyema/idp/pull/104 merged as c553b34.\n"
    )
    good2 = (
        "DONE: you ran the vision route and confirmed it.\n"
        "Founder receipt: crew#219 comment 5414486390, 'works'.\n"
        "Evidence: https://github.com/chidionyema/idp/pull/104\n"
    )
    working = "WORKING: waiting on CI.\n"
    staged = (
        "STAGED: platform/access apply (idp#150) is ready. Reply 'go' to execute immediately, 'hold' to "
        "review. Auto-activating in 60 minutes.\n"
    )
    staged_bad = "STAGED: platform/access apply is ready, say go.\n"
    # DoD v3: a live/deployment claim backed only by a test command is not evidence it's live.
    live_bad = (
        "INVENTORY: fleetview backend is packaged.\n"
        "Built: FleetView backend, on cluster and doored.\n"
        "Use: open the FleetView page in Backstage.\n"
        "Expect: a live agent roster.\n"
        "Not done: nothing.\n"
        "Evidence: `pytest tests/test_fleetview.py` all green.\n"
    )
    live_good = (
        "INVENTORY: fleetview backend is packaged.\n"
        "Built: FleetView backend, on cluster and doored.\n"
        "Use: open the FleetView page in Backstage.\n"
        "Expect: a live agent roster.\n"
        "Not done: nothing.\n"
        "Evidence: `idp-kube get deploy fleetview-backend -n backstage` shows 1/1 Running.\n"
    )
    # DoD v3 final cut: the exact FleetView-fork shape -- a curl the builder ran against its own
    # localhost daemon is not independent evidence, however real the response.
    live_bad2 = (
        "DONE: fleetview-backend is deployed and reachable.\n"
        "Founder receipt: I confirmed it myself.\n"
        "Evidence: `curl http://127.0.0.1:18790/health` -> 200 OK.\n"
    )
    live_good2 = (
        "INVENTORY: fleetview backend is packaged.\n"
        "Built: FleetView backend, on cluster and doored.\n"
        "Use: open the FleetView page in Backstage.\n"
        "Expect: a live agent roster.\n"
        "Not done: nothing.\n"
        "Evidence: qa-agent ticked the box in `~/.claude/state/qa-agent.json` after a real green "
        "run against the cluster deployment.\n"
    )
    ok = True
    for name, text, expect_block in (
        ("bad", bad, True),
        ("bad2", bad2, True),
        ("good", good, False),
        ("good2", good2, False),
        ("working", working, False),
        ("staged", staged, False),
        ("staged_bad", staged_bad, True),
        ("live_bad", live_bad, True),
        ("live_good", live_good, False),
        ("live_bad2", live_bad2, True),
        ("live_good2", live_good2, False),
    ):
        got = bool(offences(text))
        print(
            f"{name}: {'BLOCK' if got else 'PASS'} {'ok' if got == expect_block else 'WRONG'}"
        )
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
