#!/usr/bin/env python3
"""Refuse a reply that names a pull request whose checks are not green (R61).

WHY. Founder, 2026-08-31, verbatim: "looks NEVER tell nne about pr UNTIL green. Enforce it."
And in the same hour: "u build sonethig, nake sure it passes checks", "no point telling ne
just to se it red", "so check ur own work". idp pull request 1077 was named to him three
times while its gates were still red; every mention handed him triage instead of a
capability.

WHAT IT ENFORCES, on the last assistant message: a GitHub pull-request URL may appear only
when every check on that pull request is green (all completed, none failing, none still
running). A reply naming a red or in-flight pull request is refused with the rewrite: say
what capability is being built, work the pull request to green silently, and name it once,
with the green run.

WHAT IT CANNOT SEE (LAW 45 step 5). A pull request named without its URL ("the portal pull
request", "idp#1077") passes — the transcript is graded, not the author's intent. When `gh`
fails or times out the reply goes through: a guard that cannot measure must not block
(LAW 38); the pull-request page stays the surface of record. Never blocks the same text
twice, at most three blocks per session, so it cannot wedge a session.

  python3 pr-green-guard.py --selftest
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / ".claude" / "state" / "pr-green-guard.json"
MAX_BLOCKS_PER_SESSION = 3
MAX_LOOKUPS = 3
GH_TIMEOUT_S = 5

PULL_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)\b")

OK_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
OK_STATES = {"SUCCESS"}
PENDING_STATES = {"PENDING", "EXPECTED"}


def pull_urls(text: str) -> list[tuple[str, str, str]]:
    seen: list[tuple[str, str, str]] = []
    for m in PULL_URL.finditer(text):
        key = (m.group(1), m.group(2), m.group(3))
        if key not in seen:
            seen.append(key)
    return seen[:MAX_LOOKUPS]


def grade(rollup: list[dict]) -> str:
    """green, red or pending, over the LAST run of each named check (a superseded
    cancelled run must not shadow its green rerun, statuscheckrollup keeps both)."""
    last: dict[str, dict] = {}
    for entry in rollup or []:
        name = entry.get("name") or entry.get("context") or ""
        last[name] = entry
    verdict = "green"
    for entry in last.values():
        if "state" in entry:  # a commit status, not a check run
            state = (entry.get("state") or "").upper()
            if state in OK_STATES:
                continue
            if state in PENDING_STATES:
                verdict = "pending" if verdict == "green" else verdict
                continue
            return "red"
        status = (entry.get("status") or "").upper()
        conclusion = (entry.get("conclusion") or "").upper()
        if status and status != "COMPLETED":
            verdict = "pending" if verdict == "green" else verdict
            continue
        if conclusion not in OK_CONCLUSIONS:
            return "red"
    return verdict


def fetch_rollup(owner: str, repo: str, num: str) -> list[dict] | None:
    try:
        out = subprocess.run(  # noqa: S603
            [
                "gh",
                "pr",
                "view",
                num,
                "-R",
                f"{owner}/{repo}",  # noqa: S607
                "--json",
                "statusCheckRollup",
            ],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_S,
            check=False,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout).get("statusCheckRollup") or []
    except Exception:  # noqa: BLE001  (fail open: cannot measure, must not block)
        return None


def offences(text: str, fetch=fetch_rollup) -> list[str]:
    out = []
    for owner, repo, num in pull_urls(text):
        rollup = fetch(owner, repo, num)
        if rollup is None:
            continue
        verdict = grade(rollup)
        if verdict != "green":
            out.append(
                f"{owner}/{repo} pull request {num} is {verdict}; the founder hears about a "
                "pull request once, when it is green. Name the capability being built "
                "instead, finish the checks, then name the URL with its green run."
            )
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
    lines = [
        'BLOCKED by pr-green-guard (R61, founder 2026-08-31: "NEVER tell me about a pr UNTIL green"):'
    ]
    lines += [f"  - {f}" for f in found]
    return "\n".join(lines)


def selftest() -> int:
    green = [
        {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "skip", "status": "COMPLETED", "conclusion": "SKIPPED"},
    ]
    red = [{"name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}]
    superseded = [
        {"name": "ci", "status": "COMPLETED", "conclusion": "CANCELLED"},
        {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"},
    ]
    pending = [{"name": "ci", "status": "IN_PROGRESS", "conclusion": ""}]
    status_red = [{"context": "dco", "state": "FAILURE"}]
    url = "see https://github.com/o/r/pull/9 for the change"
    cases = (
        ("green", url, green, False),
        ("red", url, red, True),
        ("superseded-cancel", url, superseded, False),
        ("pending", url, pending, True),
        ("status-red", url, status_red, True),
        ("no-url", "INVENTORY: portal doors fixed.", green, False),
        ("gh-down", url, None, False),
    )
    ok = True
    for name, text, rollup, expect_block in cases:
        got = bool(offences(text, fetch=lambda *_a, r=rollup: r))
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
    if not text or not PULL_URL.search(text):
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
