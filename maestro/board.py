#!/usr/bin/env python3
"""The one board. Both minds write here; neither imports the other.

estate/ senses and writes ~/.claude/state/estate-audit.json.
maestro/ reads that JSON and writes issues here. The issue IS the message bus,
and the column an issue sits in IS the state of the work.

Columns are labels, so the board opens on a phone with no extra product:
  maestro:backlog      finding detected, not yet triaged
  maestro:triage       LAW_CONTEXT applied, shape matched or novel
  maestro:auto-fix     reversible, skill available, executing
  maestro:needs-chidi  irreversible, P0, or law violation -- the human gate
  maestro:verify       re-sensing to confirm the fix held
  maestro:done         verified, logged to the experience graph

Auth is the gh CLI's own session. No token lives in this file or in Config.

    board.py --ensure-labels          create the six columns (idempotent)
    board.py --list                   what is on the board, by column
    board.py --selftest               prove it works, change nothing
"""

import os
import sys
import json
import re
import hashlib
import subprocess
from typing import Optional, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from models import Config, logger

BACKLOG = "maestro:backlog"
TRIAGE = "maestro:triage"
AUTO_FIX = "maestro:auto-fix"
NEEDS_CHIDI = "maestro:needs-chidi"
VERIFY = "maestro:verify"
DONE = "maestro:done"

UMBRELLA = "maestro"          # every board issue carries this; it is what --list filters on

COLUMNS = [BACKLOG, TRIAGE, AUTO_FIX, NEEDS_CHIDI, VERIFY, DONE]
COLOURS = {UMBRELLA: "0052cc", BACKLOG: "ededed", TRIAGE: "fbca04", AUTO_FIX: "0e8a16",
           NEEDS_CHIDI: "b60205", VERIFY: "1d76db", DONE: "5319e7"}
DESCRIPTIONS = {
    UMBRELLA: "Opened and moved by the Maestro deputy",
    BACKLOG: "Detected, not yet triaged",
    TRIAGE: "Laws applied, shape matched or novel",
    AUTO_FIX: "Reversible, skill available, executing",
    NEEDS_CHIDI: "Irreversible, P0 or law violation -- your tap",
    VERIFY: "Re-sensing to confirm the fix held",
    DONE: "Verified, logged to the experience graph",
}

FP_PREFIX = "<!-- maestro:fp="

# LAW 21: a secret value never appears anywhere it can be read again, and an
# issue body is the most readable place there is. Every string that leaves this
# module for GitHub goes through _redact first -- body, comment and title alike.
# The finding still says which key type and which file. That is what a person
# needs to rotate it; the value is what they must never be shown.
SECRET_SHAPES = [
    (re.compile(r"sk-ant-api[0-9A-Za-z\-_]{20,}"), "sk-ant-api[REDACTED]"),
    (re.compile(r"sk_live_[0-9A-Za-z]{10,}"), "sk_live_[REDACTED]"),
    (re.compile(r"sk-[0-9A-Za-z]{32,}"), "sk-[REDACTED]"),
    (re.compile(r"hf_[0-9A-Za-z]{20,}"), "hf_[REDACTED]"),
    (re.compile(r"ghp_[0-9A-Za-z]{20,}"), "ghp_[REDACTED]"),
    (re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"), "gh*_[REDACTED]"),
    (re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}"), "xox*-[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[REDACTED JWT]"),
]


def _redact(text: str) -> str:
    for pattern, replacement in SECRET_SHAPES:
        text = pattern.sub(replacement, text)
    return text


class BoardError(RuntimeError):
    pass


def _gh(args: List[str], check: bool = True) -> str:
    """One gh call. Never raises on a missing gh; raises BoardError with the stderr."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise BoardError("gh CLI is not installed; the board is unreachable")
    except subprocess.TimeoutExpired:
        raise BoardError(f"gh timed out: {' '.join(args[:3])}")
    if check and r.returncode != 0:
        raise BoardError(f"gh {' '.join(args[:3])} failed rc={r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout


def fingerprint(finding: Dict) -> str:
    """What makes two findings the same finding. Not the timestamp, not the count."""
    key = "|".join(str(finding.get(k, "")) for k in ("check", "id", "category", "description"))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def ensure_labels(repo: Optional[str] = None) -> List[str]:
    repo = repo or Config.GITHUB_REPO
    made = []
    for col in [UMBRELLA, *COLUMNS]:
        out = subprocess.run(
            ["gh", "label", "create", col, "--repo", repo,
             "--color", COLOURS[col], "--description", DESCRIPTIONS[col]],
            capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            made.append(col)
        elif "already exists" not in (out.stderr + out.stdout):
            raise BoardError(f"label {col}: {out.stderr.strip()[:200]}")
    return made


def find_by_fingerprint(fp: str, repo: Optional[str] = None) -> Optional[int]:
    """An open issue already carrying this fingerprint, or None. Stops duplicate noise."""
    repo = repo or Config.GITHUB_REPO
    raw = _gh(["issue", "list", "--repo", repo, "--state", "all",
               "--label", "maestro", "--limit", "200",
               "--json", "number,body"])
    for issue in json.loads(raw or "[]"):
        if f"{FP_PREFIX}{fp}" in (issue.get("body") or ""):
            return issue["number"]
    return None


def acknowledged(finding: Dict, repo: Optional[str] = None) -> bool:
    """True once a P0 is on the board and sitting in the human gate.

    Crisis is meant to stop the estate until a person looks. It is not meant to
    stop it forever. Once the P0 is an open issue in needs-chidi, the founder has
    it; re-entering crisis on every tick after that only guarantees the other
    findings are never sensed, which is the failure this check exists to prevent.
    """
    repo = repo or Config.GITHUB_REPO
    fp = fingerprint(finding)
    raw = _gh(["issue", "list", "--repo", repo, "--state", "open",
               "--label", NEEDS_CHIDI, "--limit", "200", "--json", "number,body"])
    return any(f"{FP_PREFIX}{fp}" in (i.get("body") or "") for i in json.loads(raw or "[]"))


def open_finding(finding: Dict, column: str = BACKLOG, repo: Optional[str] = None) -> int:
    """Put a finding on the board, or return the issue that already holds it."""
    repo = repo or Config.GITHUB_REPO
    fp = fingerprint(finding)
    existing = find_by_fingerprint(fp, repo)
    if existing:
        return existing

    sev = str(finding.get("severity", finding.get("priority", "P2"))).upper()
    title = f"[{sev}] {finding.get('description') or finding.get('check') or 'estate finding'}"[:240]
    body = "\n".join([
        f"**Sensed by** `estate/estate_audit.py`",
        f"**Check** `{finding.get('check', finding.get('id', 'unknown'))}`",
        f"**Severity** {sev}",
        "",
        "```json",
        json.dumps(finding, indent=2, default=str)[:4000],
        "```",
        "",
        "_Maestro moves this issue between columns. The column is the state._",
        "",
        f"{FP_PREFIX}{fp} -->",
    ])
    out = _gh(["issue", "create", "--repo", repo, "--title", _redact(title),
               "--body", _redact(body), "--label", "maestro", "--label", column])
    num = int(out.strip().rstrip("/").split("/")[-1])
    logger.info(f"board: opened #{num} in {column}")
    return num


def move(number: int, column: str, note: str = "", repo: Optional[str] = None) -> None:
    """One column at a time. Removing the others is what makes the board readable."""
    if column not in COLUMNS:
        raise BoardError(f"unknown column: {column}")
    repo = repo or Config.GITHUB_REPO
    args = ["issue", "edit", str(number), "--repo", repo, "--add-label", column]
    for other in COLUMNS:
        if other != column:
            args += ["--remove-label", other]
    _gh(args)
    if note:
        comment(number, note, repo)
    if column == DONE:
        _gh(["issue", "close", str(number), "--repo", repo, "--reason", "completed"])
    logger.info(f"board: #{number} -> {column}")


def comment(number: int, text: str, repo: Optional[str] = None) -> None:
    repo = repo or Config.GITHUB_REPO
    _gh(["issue", "comment", str(number), "--repo", repo, "--body", _redact(text)[:60000]])


def post_intent(number: int, intent: Dict, repo: Optional[str] = None) -> None:
    """The white-box record: what Maestro decided, under which laws, and what came back.

    THE-ARCHITECT says verification is by execution. This comment is where the
    command and its output live, so the board entry is the proof and not a claim.
    """
    lines = [f"**INTENT `{intent.get('id')}`**", ""]
    if intent.get("laws_applied"):
        lines.append(f"Laws applied: {', '.join(intent['laws_applied'])}")
    if intent.get("state"):
        lines.append(f"State: `{intent['state']}`")
    if intent.get("hypothesis"):
        lines.append(f"Hypothesis: {intent['hypothesis']}")
    ev = intent.get("evidence") or {}
    if ev.get("stdout") or ev.get("stderr"):
        lines += ["", "```", (ev.get("stdout") or "")[:1500], (ev.get("stderr") or "")[:500], "```"]
    comment(number, "\n".join(lines), repo)


def summary(repo: Optional[str] = None) -> Dict[str, int]:
    repo = repo or Config.GITHUB_REPO
    raw = _gh(["issue", "list", "--repo", repo, "--state", "all",
               "--label", "maestro", "--limit", "300", "--json", "number,labels,state"])
    counts = {c: 0 for c in COLUMNS}
    for issue in json.loads(raw or "[]"):
        for lab in issue.get("labels", []):
            if lab["name"] in counts:
                counts[lab["name"]] += 1
    return counts


def _selftest() -> int:
    fails = []
    a = {"check": "disk_free", "severity": "P1", "description": "disk 96% full"}
    b = dict(a, timestamp="2026-08-22T13:00:00")
    if fingerprint(a) != fingerprint(b):
        fails.append("fingerprint moved when only the timestamp changed")
    c = dict(a, check="bridge_down")
    if fingerprint(a) == fingerprint(c):
        fails.append("fingerprint collided across different checks")
    if len(set(COLUMNS)) != 6:
        fails.append("the board does not have six distinct columns")
    try:
        who = _gh(["auth", "status"], check=False)
        reachable = _gh(["repo", "view", Config.GITHUB_REPO, "--json", "name"], check=False)
        if not reachable.strip():
            fails.append(f"cannot reach {Config.GITHUB_REPO} with the gh session")
    except BoardError as exc:
        fails.append(str(exc))
    if fails:
        print("board selftest FAILED:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(f"board selftest: all passed; repo {Config.GITHUB_REPO} reachable, 6 columns, fingerprint stable")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="The one board")
    ap.add_argument("--ensure-labels", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ns = ap.parse_args()
    if ns.selftest:
        sys.exit(_selftest())
    if ns.ensure_labels:
        made = ensure_labels()
        print(f"created: {made or 'nothing, all six already there'}")
    if ns.list:
        for col, n in summary().items():
            print(f"  {col:<22} {n}")
