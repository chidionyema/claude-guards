#!/usr/bin/env python3
"""PostToolUse hook: capture a research pass without being asked (crew#72).

`directive-capture.py` records what the founder asked; nothing recorded what a session
went and read. `decision-log.py` was the writer nobody wired: 132 rows, every one typed
by hand, none since 2026-08-25. This hook runs after every WebSearch and WebFetch and
records the search or the source on the session's open research row through that same
writer, so the trail exists whether or not the session remembers LAW 35.

One research row per session, kept in `~/.claude/state/research-capture/<session>.rid`;
its question is the first search the session ran. The hook never blocks a tool: every
failure is swallowed to stderr and the exit code is 0.

Env: DECISION_LOG (test override, same as decision-log.py), RESEARCH_CAPTURE_STATE.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

HOME = Path(os.environ.get("CLAUDE_HOME") or Path.home())
WRITER = Path(__file__).resolve().parent / "decision-log.py"
STATE = Path(os.environ.get("RESEARCH_CAPTURE_STATE") or (HOME / ".claude/state/research-capture"))

#: Publisher tier from the host. Not a judgement of quality: the tiers are decision-log's
#: own and the fallback is the lowest one, so a session that wants a source graded higher
#: re-records it with `decision-log.py --source ... --tier`.
TIER_BY_HOST = (
    (("arxiv.org", "doi.org", "acm.org", "ieee.org", "nature.com", "usenix.org"), "peer-reviewed"),
    (("ietf.org", "w3.org", "iso.org", "nist.gov", "owasp.org"), "standard"),
    (("docs.", "readthedocs", "kubernetes.io", "python.org", "github.com", "developer."), "docs"),
    (("reuters.com", "bbc.co", "ft.com", "theregister.com"), "news"),
)


def tier_for(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for needles, tier in TIER_BY_HOST:
        if any(n in host for n in needles):
            return tier
    return "blog"


def writer(args: list[str]) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(WRITER), *args], capture_output=True, text=True, timeout=20)
    return p.returncode, (p.stdout or p.stderr).strip()


def rid_for(session: str, question: str) -> str | None:
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / f"{session or 'unknown'}.rid"
    if f.exists() and f.read_text().strip():
        return f.read_text().strip()
    rc, out = writer(["--research", question[:200]])
    if rc or not out:
        return None
    f.write_text(out.splitlines()[-1].strip())
    return f.read_text().strip()


def capture(payload: dict) -> str:
    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") or {}
    session = str(payload.get("session_id") or "")[:8]
    if tool == "WebSearch":
        q = str(inp.get("query") or "").strip()
        if not q:
            return "skip: empty query"
        rid = rid_for(session, q)
        if not rid:
            return "skip: no research row"
        resp = payload.get("tool_response")
        n = len(resp) if isinstance(resp, list) else 0
        rc, out = writer(["--search", rid, "-q", q, "--engine", "websearch", "-n", str(n)])
        return out if not rc else f"writer refused: {out}"
    if tool == "WebFetch":
        url = str(inp.get("url") or "").strip()
        if not url:
            return "skip: empty url"
        rid = rid_for(session, str(inp.get("prompt") or url)[:200])
        if not rid:
            return "skip: no research row"
        host = urlparse(url).hostname or url
        rc, out = writer(["--source", rid, "--url", url, "--title", url[:120], "--publisher", host,
                          "--tier", tier_for(url), "--claim", str(inp.get("prompt") or "")[:300]])
        return out if not rc else f"writer refused: {out}"
    return f"skip: {tool}"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:                                            # noqa: BLE001
        return 0
    try:
        msg = capture(payload)
        if not msg.startswith("skip"):
            print(f"[research-capture] {msg}", file=sys.stderr)
    except Exception as exc:                                     # noqa: BLE001
        print(f"[research-capture] BLIND: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
