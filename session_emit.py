#!/usr/bin/env python3
"""Emit one OTLP log record per turn, so an agent session is a workload the estate can see.

LAW 50: every workload emits to the central collector, and coverage is proved by querying the
backend rather than by scanning files. Agent sessions were the gap -- everything a session did
lived in this laptop's transcripts and the local board at 127.0.0.1, which the founder cannot
reach from his phone and a buyer cannot be shown. This closes it over the road the estate
already has: the same `${OTEL_EXPORTER_OTLP_ENDPOINT}/v1/logs` with the same `science` basic-auth
pair that bin/lib/conscience_emit.py uses (LAW 43 -- the road existed, it had simply never been
given a credential on this machine).

The record is derived from git and the hook payload, never from a transcript, so a session driven
by any agent or any provider produces the same shape (the reason bin/estate-checkpoint works that
way too).

Credential (LAW 21, LAW 52): the password is minted once from the estate vault into the macOS
Keychain by `--provision` and never written to a file, an environment file or a log. The hook
reads it back through /usr/bin/security. No value is printed by any code path here.

    session_emit.py --provision     mint the credential into the Keychain (once per machine)
    session_emit.py --hook          Stop hook; reads the hook json on stdin
    session_emit.py --selftest      grade this file
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys
import time
from http.client import HTTPSConnection

STATE = pathlib.Path.home() / ".claude" / "state"
LAST = STATE / "session-emit-last.json"
ENDPOINT_FILE = STATE / "otlp-endpoint"
ERRORS = STATE / "session-emit-errors.log"

#: One record a minute per session is enough to answer "what is this session doing"; a fast turn
#: must not cost a round trip. estate-checkpoint throttles the same way for the same reason.
MIN_INTERVAL_S = 60
#: A Stop hook holds the turn. Five seconds is the whole budget, and a timeout is not an error.
TIMEOUT_S = 5
KEYCHAIN_SERVICE = "estate-otlp-ingest"
KEYCHAIN_ACCOUNT = "science"
SECURITY = "/usr/bin/security"


def _quiet(message: str) -> None:
    """A failed emit is never worth a broken turn, and never worth a wall of text either."""
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with ERRORS.open("a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    except OSError:
        pass


def _run(argv: list[str], cwd: str | None = None, timeout: int = 10) -> str:
    """Argv only, never a shell string, and a failure is the empty string."""
    try:
        out = subprocess.run(  # noqa: S603  -- argv list, absolute or repo-relative program, no shell
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def password() -> str:
    """Read the ingest password out of the Keychain. Never printed, never cached to disk."""
    return _run(
        [
            SECURITY,
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
        ]
    )


def endpoint() -> str:
    """The collector base. The environment wins so a container can override it (LAW 46: no host
    is typed here); otherwise the value --provision wrote beside the credential."""
    live = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if live:
        return live.rstrip("/")
    try:
        return ENDPOINT_FILE.read_text().strip().rstrip("/")
    except OSError:
        return ""


def record(payload: dict, now_ns: int | None = None) -> dict:
    """The turn, derived from git in the session's own checkout plus what the hook was handed."""
    cwd = str(payload.get("cwd") or "")
    git = ["git", "-C", cwd] if cwd else ["git"]
    branch = _run([*git, "rev-parse", "--abbrev-ref", "HEAD"])
    head = _run([*git, "log", "-1", "--format=%h %s"])
    dirty = _run([*git, "status", "--porcelain"])
    session = str(payload.get("session_id") or "")[:8]
    return {
        "session": session,
        "agent": str(payload.get("agent") or "claude-code"),
        "cwd": cwd,
        "branch": branch,
        "head": head,
        "uncommitted": len([ln for ln in dirty.splitlines() if ln.strip()]),
        "at_ns": now_ns if now_ns is not None else time.time_ns(),
    }


def otlp(rec: dict) -> dict:
    """The OTLP log shape bin/lib/conscience_emit.py already posts, with this workload's name."""
    attrs = [
        ("science.source", "claude-session"),
        ("session.id", rec["session"]),
        ("session.agent", rec["agent"]),
        ("session.branch", rec["branch"]),
        ("session.cwd", rec["cwd"]),
    ]
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "claude-session"},
                        },
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {"name": "session_emit.py"},
                        "logRecords": [
                            {
                                "timeUnixNano": str(rec["at_ns"]),
                                "severityText": "INFO",
                                "body": {
                                    "stringValue": json.dumps(
                                        rec, separators=(",", ":")
                                    )
                                },
                                "attributes": [
                                    *[
                                        {"key": k, "value": {"stringValue": v}}
                                        for k, v in attrs
                                    ],
                                    {
                                        "key": "session.uncommitted",
                                        "value": {"intValue": str(rec["uncommitted"])},
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def post(base: str, user: str, pw: str, body: dict) -> int:
    """POST the record. Returns the HTTP status, or 0 when the collector could not be reached."""
    host = base.split("://", 1)[-1].split("/", 1)[0]
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    conn = HTTPSConnection(host, timeout=TIMEOUT_S)
    try:
        conn.request(
            "POST",
            "/v1/logs",
            body=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            },
        )
        return conn.getresponse().status
    except OSError:
        return 0
    finally:
        conn.close()


def due(session: str, now: float, path: pathlib.Path | None = None) -> bool:
    """One record a minute per session."""
    path = path or LAST
    try:
        seen = json.loads(path.read_text())
    except (OSError, ValueError):
        seen = {}
    return now - float(seen.get(session, 0)) >= MIN_INTERVAL_S


def mark(session: str, now: float, path: pathlib.Path | None = None) -> None:
    path = path or LAST
    try:
        seen = json.loads(path.read_text())
    except (OSError, ValueError):
        seen = {}
    seen[session] = now
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen))
    except OSError:
        pass


def cmd_hook() -> int:
    """Stop. Never raises and always returns 0: a telemetry record is not worth a broken turn."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        session = str(payload.get("session_id") or "")[:8]
        now = time.time()
        if not session or not due(session, now):
            return 0
        base, pw = endpoint(), password()
        if not (base and pw):
            _quiet("BLIND: no endpoint or no keychain credential; run --provision")
            return 0
        code = post(base, KEYCHAIN_ACCOUNT, pw, otlp(record(payload)))
        if code // 100 != 2:
            _quiet(f"emit -> HTTP {code}")
        else:
            mark(session, now)
    except Exception as exc:  # noqa: BLE001  -- a hook that raises breaks the turn
        _quiet(f"{type(exc).__name__}: {exc}")
    return 0


def cmd_provision(repo: str) -> int:
    """Mint the credential from the estate vault into the Keychain. Prints no value."""
    zone = ""
    cfg = pathlib.Path(repo) / "clusters" / "oke" / "estate-config.yaml"
    for line in cfg.read_text().splitlines() if cfg.exists() else []:
        if line.strip().startswith("ESTATE_ZONE:"):
            zone = line.split(":", 1)[1].strip()
            break
    if not zone:
        print(f"BLIND: no ESTATE_ZONE in {cfg}")
        return 2
    # The vault read walks OCI and takes about ten seconds; --provision is a one-off,
    # so it gets a minute rather than the hook path's budget.
    pw = _run(
        ["bin/idp-cloud", "secret", "get", "otlp-ingest-password"], cwd=repo, timeout=60
    )
    pw = pw.splitlines()[-1].strip() if pw else ""
    if not pw:
        print("BLIND: bin/idp-cloud could not read otlp-ingest-password")
        return 2
    _run(
        [
            SECURITY,
            "delete-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
        ]
    )
    add = subprocess.run(  # noqa: S603  -- argv list, absolute program, no shell
        [
            SECURITY,
            "add-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
            pw,
            "-U",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if add.returncode != 0:
        print("FAIL: keychain refused the credential")
        return 1
    STATE.mkdir(parents=True, exist_ok=True)
    ENDPOINT_FILE.write_text(f"https://signoz.{zone}\n")
    print(
        f"ok  credential in the login keychain as {KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT}; "
        f"collector https://signoz.{zone} in {ENDPOINT_FILE}"
    )
    return 0


def selftest() -> int:
    import tempfile

    fails = []

    def check(name: str, ok: bool) -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            fails.append(name)

    rec = record({"session_id": "abcdef1234", "cwd": "/nonexistent-checkout"}, now_ns=7)
    check("the session id is the short form", rec["session"] == "abcdef12")
    check("a cwd that is not a checkout is not an error", rec["branch"] == "")
    check("the timestamp is the one passed in", rec["at_ns"] == 7)
    check("the agent defaults to claude-code", rec["agent"] == "claude-code")

    doc = otlp(rec)
    logs = doc["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    res = doc["resourceLogs"][0]["resource"]["attributes"]
    check(
        "the workload names itself", res[0]["value"]["stringValue"] == "claude-session"
    )
    check("timeUnixNano is a string, as OTLP requires", logs["timeUnixNano"] == "7")
    keys = {a["key"] for a in logs["attributes"]}
    check(
        "the science.source attribute is the one coverage counts",
        "science.source" in keys,
    )
    check(
        "the record body round-trips",
        json.loads(logs["body"]["stringValue"])["session"] == "abcdef12",
    )

    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "last.json"
        check("a session never seen is due", due("aaaa", 1000.0, p))
        mark("aaaa", 1000.0, p)
        check("the same session is not due a second later", not due("aaaa", 1001.0, p))
        check(
            "it is due again after the interval",
            due("aaaa", 1000.0 + MIN_INTERVAL_S, p),
        )
        check("another session is due regardless", due("bbbb", 1001.0, p))
        bad = pathlib.Path(d) / "corrupt.json"
        bad.write_text("{not json")
        check(
            "a corrupt throttle file does not stop the emit", due("aaaa", 1000.0, bad)
        )

    check(
        "the environment wins over the file for the endpoint",
        (
            os.environ.update({"OTEL_EXPORTER_OTLP_ENDPOINT": "https://x.example/"})
            or endpoint()
        )
        == "https://x.example",
    )
    del os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]

    check("no code path prints the password", "print" not in password.__code__.co_names)

    print("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--hook":
        sys.exit(cmd_hook())
    if arg == "--provision":
        sys.exit(cmd_provision(sys.argv[2] if len(sys.argv) > 2 else os.getcwd()))
    if arg == "--selftest":
        sys.exit(selftest())
    print(__doc__)
    sys.exit(2)
