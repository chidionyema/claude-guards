#!/usr/bin/env python3
"""estate-state-guard.py -- crew#648 CP4: every session starts with the state of the estate.

SessionStart: call `get_estate_state` on the estate MCP (the server and its bearer come from the
harness's own MCP config, never a literal here, LAW 46), cache the document under ~/.estate and
print a plain-English summary as context: age, stale flag, the production cluster's verdict and
its red Flux rows, red surfaces, open P0s, freeze. A server that cannot be reached is a BLIND line,
never a quiet green (silent-green is the incident class, crew#668).

Stop: the reply's status may not contradict the document. When the cached document (under 30
minutes old) says the production cluster or a routed surface is red and the reply says the estate,
the cluster or the platform is green, the reply is refused with the rows that say otherwise.
A refusal is once per reply, twice per session at most, like dod-guard.

Self-test: `python3 estate-state-guard.py --selftest`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("HOME", "~")).expanduser()
CACHE = HOME / ".estate" / "estate-state.json"
STATE = HOME / ".estate" / "estate-state-guard.json"
TIMEOUT = 8
FRESH_MINUTES = 30
GREEN_CLAIM = re.compile(
    r"\b(estate|cluster|platform|production|prod)\b[^.\n]{0,40}\b(is|are|all|reads?|looks?)\s+green\b|\ball green\b",
    re.I,
)


def server() -> tuple[str, dict]:
    """The estate MCP endpoint and headers from the harness config -- the same connection the
    session's own `mcp__estate__*` tools use."""
    cfg = json.loads((HOME / ".claude.json").read_text())
    est = (cfg.get("mcpServers") or {}).get("estate") or {}
    url = est.get("url") or ""
    if not url:
        raise LookupError("no mcpServers.estate.url in ~/.claude.json")
    return url, dict(est.get("headers") or {})


def _post(url: str, headers: dict, body: dict, session_id: str | None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **headers,
    }
    if session_id:
        h["Mcp-Session-Id"] = session_id
    if not url.startswith("https://"):
        raise ValueError("the estate MCP must be an https URL")
    req = urllib.request.Request(  # noqa: S310
        url, data=json.dumps(body).encode(), headers=h, method="POST"
    )  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
        sid = r.headers.get("Mcp-Session-Id") or session_id
        raw = r.read().decode("utf-8", errors="replace")
        ctype = r.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        msgs = [
            json.loads(line[5:].strip())
            for line in raw.splitlines()
            if line.startswith("data:")
        ]
        return sid, (msgs[-1] if msgs else {})
    return sid, (json.loads(raw) if raw.strip() else {})


def fetch() -> dict:
    """The MCP handshake, then tools/call get_estate_state. Returns the tool's JSON."""
    url, headers = server()
    sid, _ = _post(
        url,
        headers,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "estate-state-guard", "version": "1"},
            },
        },
        None,
    )
    try:
        _post(
            url, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid
        )
    except urllib.error.HTTPError:
        pass  # some servers answer 202 or 405 to the notification; the call below is the test
    _, resp = _post(
        url,
        headers,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_estate_state", "arguments": {}},
        },
        sid,
    )
    result = resp.get("result") or {}
    if result.get("structuredContent"):
        return result["structuredContent"]
    for block in result.get("content") or []:
        if block.get("type") == "text":
            return json.loads(block["text"])
    raise ValueError("tools/call returned no content: %s" % json.dumps(resp)[:200])


def red_rows(doc: dict) -> list[str]:
    out = []
    rt = doc.get("runtime") or {}
    for c in rt.get("clusters") or []:
        if str(c.get("state", "")).upper() != "OK":
            out.append(
                "cluster %s (%s): %s" % (c.get("name"), c.get("role"), c.get("state"))
            )
            for r in c.get("flux_rows") or []:
                if not r.get("ready"):
                    out.append(
                        "  %s/%s %s: %s"
                        % (
                            r.get("namespace"),
                            r.get("name"),
                            r.get("kind"),
                            str(r.get("message"))[:110],
                        )
                    )
    for s in rt.get("surfaces") or []:
        if str(s.get("verdict", "")).lower() != "ok":
            out.append(
                "surface %s %s: %s"
                % (s.get("name"), s.get("verdict"), str(s.get("detail"))[:110])
            )
    for p in (doc.get("delivery") or {}).get("open_p0") or []:
        out.append("open P0: %s" % (p.get("title") if isinstance(p, dict) else p))
    if ((doc.get("overview") or {}).get("freeze") or {}).get("active"):
        out.append("FREEZE is active")
    return out


def summary(state: dict) -> str:
    if not state.get("available"):
        return (
            "[estate-state] BLIND: the estate MCP has no document (%s). Nothing here is green."
            % state.get("error")
        )
    doc = state.get("document") or {}
    age = state.get("age_minutes")
    head = "[estate-state] crew#648: state of the estate at %s (%.0f min old%s)." % (
        doc.get("generated_at"),
        age or 0,
        ", STALE: older than the 30-minute line, treat as unknown"
        if state.get("stale")
        else "",
    )
    rows = red_rows(doc)
    sessions = [
        s
        for s in ((doc.get("overview") or {}).get("sessions") or [])
        if not str(s.get("active", "")).startswith("parked")
    ]
    lines = [head]
    lines += (
        (
            ["  RED rows, the first status line may not contradict these:"]
            + ["  " + r for r in rows]
        )
        if rows
        else [
            "  no red row: production cluster OK, every routed surface ok, no open P0."
        ]
    )
    lines.append(
        "  main: %s; active sessions: %d; rulings on record: %d."
        % (
            ", ".join(
                "%s=%s" % (k, v[:8])
                for k, v in ((doc.get("delivery") or {}).get("main_sha") or {}).items()
            ),
            len(sessions),
            len((doc.get("overview") or {}).get("rulings") or []),
        )
    )
    # The whole estate, structured, nothing left out (founder 2026-08-30: "you need to ingest
    # the whole estate in structured format"). The red rows above are the index; this is the record.
    lines.append("  Document, verbatim JSON:")
    lines.append(json.dumps(state, indent=1, sort_keys=True))
    lines.append("  Live read: mcp__estate__get_estate_state; cached at %s." % CACHE)
    return "\n".join(lines)


def session_start() -> int:
    try:
        state = fetch()
        state["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(state))
        print(summary(state))
    except Exception as e:  # noqa: BLE001
        print(
            "[estate-state] BLIND: get_estate_state could not be read (%s: %s). Nothing here is green until it can."
            % (type(e).__name__, str(e)[:160])
        )
    return 0


def cached() -> dict | None:
    try:
        state = json.loads(CACHE.read_text())
        at = datetime.strptime(state["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except Exception:  # noqa: BLE001
        return None
    if (datetime.now(timezone.utc) - at).total_seconds() > FRESH_MINUTES * 60:
        return None
    return state


def offences(text: str, state: dict | None) -> list[str]:
    """Rows the reply contradicts: it claims the estate is green while the fresh document is red."""
    if (
        not state
        or not state.get("available")
        or state.get("stale")
        or not GREEN_CLAIM.search(text)
    ):
        return []
    return red_rows(state.get("document") or {})


def last_assistant_text(transcript: Path) -> str:
    text = ""
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            joined = "\n".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
            if joined:
                text = joined
    return text


def stop(payload: dict) -> int:
    path = payload.get("transcript_path") or ""
    if not path or not os.path.exists(path):
        return 0
    text = last_assistant_text(Path(path))
    found = offences(text, cached())
    if not found:
        return 0
    session = str(payload.get("session_id") or "unknown")
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    try:
        st = json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        st = {}
    mine = st.get(session) or {"count": 0, "seen": []}
    if digest in mine["seen"] or mine["count"] >= 2:
        return 0
    mine["count"] += 1
    mine["seen"] = (mine["seen"] + [digest])[-20:]
    st[session] = mine
    STATE.write_text(json.dumps(st))
    print(
        "BLOCKED by estate-state-guard (crew#648 CP4): the reply calls the estate green while the estate state document says:\n  "
        + "\n  ".join(found)
        + "\nSay what is red, or say what you graded and that these rows were not it.",
        file=sys.stderr,
    )
    return 2


def check(cond: object, why: str) -> None:
    if not cond:
        raise SystemExit("estate-state-guard selftest: " + why)


def selftest() -> int:
    red = {
        "available": True,
        "stale": False,
        "document": {
            "runtime": {
                "clusters": [
                    {
                        "name": "oke",
                        "role": "production",
                        "state": "FAIL",
                        "flux_rows": [
                            {
                                "kind": "Kustomization",
                                "namespace": "flux-system",
                                "name": "tailscale",
                                "ready": False,
                                "message": "stalled",
                            }
                        ],
                    }
                ],
                "surfaces": [
                    {"name": "second-hop", "verdict": "FAIL", "detail": "did not load"}
                ],
            }
        },
    }
    check(
        offences("DONE: the estate is green and the founder used it", red),
        "green over red must be refused",
    )
    check(
        offences("INVENTORY: all green on the cluster", red),
        "offences('INVENTORY: all green on the cluster', red)",
    )
    check(
        not offences("INVENTORY: the tests are green; cluster FAIL on tailscale", red),
        "green tests are not a green estate",
    )
    check(
        not offences("DONE: estate is green", {**red, "stale": True}),
        "a stale document refuses nothing",
    )
    check(
        not offences("DONE: estate is green", None),
        "not offences('DONE: estate is green', None)",
    )
    ok = {
        "available": True,
        "stale": False,
        "document": {
            "runtime": {
                "clusters": [{"name": "oke", "role": "production", "state": "OK"}],
                "surfaces": [],
            }
        },
    }
    check(
        not offences("DONE: the estate is green", ok),
        "not offences('DONE: the estate is green', ok)",
    )
    check(
        "BLIND" in summary({"available": False, "error": "no artifact"}),
        "'BLIND' in summary({'available': False, 'error': 'no artifac",
    )
    check(
        "RED rows"
        in summary(
            {
                **red,
                "age_minutes": 3,
                "document": {**red["document"], "generated_at": "x"},
            }
        ),
        "'RED rows' in summary({**red, 'age_minutes': 3, 'document': ",
    )
    print("ok estate-state-guard selftest")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--fetch" in argv:
        state = fetch()
        print(summary(state))
        return 0 if state.get("available") and not state.get("stale") else 1
    kind = argv[0] if argv else ""
    if kind == "SessionStart":
        return session_start()
    if kind == "Stop":
        try:
            payload = json.load(sys.stdin)
        except Exception:  # noqa: BLE001
            payload = {}
        return stop(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
