#!/usr/bin/env python3
"""estate-state-relay.py -- crew#648 CP4: every session starts with the whole estate, structured.

SessionStart: call `get_estate_state` on the estate MCP (server and bearer from the harness's own
MCP config, never a literal here, LAW 46), cache the document under ~/.estate and inject it whole
as JSON, red rows first. Founder 2026-08-30: "you need to ingest the whole estate in structured
format ... that way you dont need to spend time trying to find information you already have".
A server that cannot be reached is a BLIND line, never a quiet green (crew#668).

This file decides nothing. The two refusals that read the cached document are Rego, evaluated by
opa-hook.py: policy/reply.rego refuses a reply that calls the estate green while the document says
red; policy/hooks.rego refuses a tool call that re-fetches what the document already holds.

Self-test: `python3 estate-state-relay.py --selftest`; live: `--fetch`.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("HOME", "~")).expanduser()
CACHE = HOME / ".estate" / "estate-state.json"
TIMEOUT = 8
FRESH_MINUTES = 30


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
                "clientInfo": {"name": "estate-state-relay", "version": "1"},
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


def check(cond: object, why: str) -> None:
    if not cond:
        raise SystemExit("estate-state-relay selftest: " + why)


def selftest() -> int:
    red = {
        "available": True,
        "stale": False,
        "age_minutes": 3,
        "document": {
            "generated_at": "x",
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
            },
        },
    }
    check(
        "BLIND" in summary({"available": False, "error": "no artifact"}),
        "a missing document is BLIND",
    )
    out = summary(red)
    check(
        "RED rows" in out and "tailscale" in out and "second-hop" in out,
        "red rows are listed first",
    )
    check('"generated_at": "x"' in out, "the whole document is injected, verbatim JSON")
    print("ok estate-state-relay selftest")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--fetch" in argv:
        state = fetch()
        print(summary(state))
        return 0 if state.get("available") and not state.get("stale") else 1
    if argv and argv[0] == "SessionStart":
        return session_start()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
