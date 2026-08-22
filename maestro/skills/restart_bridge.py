#!/usr/bin/env python3
"""Bring a local model bridge back and prove the port answers before claiming it.

Restarting is the easy half. This skill only exits 0 once the socket accepts a
connection, because a launchd job that starts and dies looks identical to one
that works if you only read the return code of kickstart.

    restart_bridge.py --json                    read MAESTRO_CONTEXT for the name
    restart_bridge.py --bridge kimi-bridge      name it directly
"""

import os
import sys
import json
import time
import socket
import subprocess

BRIDGES = {
    "kimi-bridge": {"job": "ai.estate.kimi-bridge", "port": 8765},
    "deepseek-bridge": {"job": "ai.estate.deepseek-bridge", "port": 8767},
    "consultd": {"job": "ai.estate.consultd", "port": 8770},
}
SETTLE_S = 20


def port_open(port: int, timeout: float = 1.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pick() -> str:
    for i, a in enumerate(sys.argv):
        if a == "--bridge" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    ctx = json.loads(os.getenv("MAESTRO_CONTEXT", "{}") or "{}")
    return ctx.get("bridge") or ctx.get("name") or ""


def main() -> int:
    name = pick()
    if name not in BRIDGES:
        print(json.dumps({"skill": "restart_bridge", "error": f"unknown bridge {name!r}",
                          "known": sorted(BRIDGES)}, indent=2))
        return 2

    spec = BRIDGES[name]
    uid = os.getuid()
    before = port_open(spec["port"])
    r = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{spec['job']}"],
                       capture_output=True, text=True, timeout=60)

    deadline = time.time() + SETTLE_S
    after = False
    while time.time() < deadline:
        if port_open(spec["port"]):
            after = True
            break
        time.sleep(1)

    evidence = {
        "skill": "restart_bridge",
        "bridge": name,
        "job": spec["job"],
        "port": spec["port"],
        "port_open_before": before,
        "port_open_after": after,
        "kickstart_rc": r.returncode,
        "kickstart_stderr": r.stderr.strip()[:400],
        "waited_s": SETTLE_S if not after else round(SETTLE_S - (deadline - time.time()), 1),
    }
    print(json.dumps(evidence, indent=2))
    return 0 if after else 1


if __name__ == "__main__":
    sys.exit(main())
