#!/usr/bin/env python3
"""Ask OPA about a hook payload. Decides nothing itself.

This file exists so that policy does not. The rules it enforces are in
policy/hooks.rego, with their cases in policy/hooks_test.rego, and OPA 1.19.1 at
/usr/local/bin evaluates them. Two Python guards were deleted to create it:
vendor-surface-guard.py (146 lines) and adr-sources-guard.py (129 lines).

It carries no guard/gate/fence in its name on purpose. Those names mean "this
file decides something", and this one does not -- it reads stdin, hands it to the
engine, and prints what comes back. If a rule ever appears below this docstring,
the migration has gone backwards.

Fails OPEN on every error, deliberately. A broken adapter must not become an
outage on every tool call in every session (LAW 38).

    echo '{"tool_name":"Artifact","tool_input":{"file_path":"/tmp/x.html"}}' \
      | python3 opa-hook.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

POLICY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy")
QUERY = "data.hooks.deny"

# policy/fixtures holds JSON test data for other policies. Loading it as --data
# collides with itself ("merge error") and OPA then reports that as an empty
# result, which a fail-open adapter reads as "permitted". Same ignore list as
# rule-guard.py, and the reason it is not optional.
IGNORE = ("fixtures", "*.json")


def denials(payload: dict) -> list[str]:
    opa = shutil.which("opa")
    if not opa:
        return []
    try:
        out = subprocess.run(
            [opa, "eval", "--strict-builtin-errors", "--format", "json",
             *sum(((["--ignore", p]) for p in IGNORE), []),
             "--data", POLICY, "--stdin-input", QUERY],
            input=json.dumps(payload), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    try:
        return list(json.loads(out.stdout)["result"][0]["expressions"][0]["value"])
    except (ValueError, KeyError, IndexError, TypeError):
        return []


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    msgs = denials(payload)
    if not msgs:
        return 0
    sys.stderr.write("\n\n".join(sorted(msgs)) + "\n")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)
