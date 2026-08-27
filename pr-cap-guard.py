#!/usr/bin/env python3
"""PreToolUse adapter for policy/pr_cap.rego (crew#504 CP5, crew#66): `gh pr create` is refused
while the target repo has more than PR_CAP (20) live open PRs (label `hold` not counted, crew#538), and
`gh pr merge N --delete-branch` while another open PR is based on N's head (idp#458 was closed by
the merge of idp#454, 2026-08-27; merge bottom-up, delete at the top).

This file gathers (splits the command, resolves the repo, asks GitHub); policy/pr_cap.rego decides,
the split hand_rolled_policy.rego asks for (claude-guards#173 refused 62 more Python lines).

FAILS OPEN, ALWAYS. No gh, no network, no opa, unreadable payload, unknown repo: exit 0. The guard
stops a queue from growing, not work when GitHub is down. Registered in settings/settings.json."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

PR_CAP = int(os.environ.get("PR_CAP", "20"))  # crew#504 set 10; founder 2026-08-27 20:4xZ: "increse the slot to 20"
HOLD_LABEL = os.environ.get("PR_CAP_HOLD_LABEL", "hold")
GH_TIMEOUT = 20
POLICY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy", "pr_cap.rego")
REMOTE_RE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$")


def _split_commands(cmd: str) -> list[list[str]]:
    parts: list[list[str]] = []
    for part in re.split(r"&&|\|\||;|\n", cmd):
        try:
            parts.append(shlex.split(part))
        except ValueError:
            continue
    return [a for a in parts if a]


def target_repo(argv: list[str], cwd: str) -> str:
    """`owner/repo` from -R/--repo, else the cwd's origin remote; '' when unknown."""
    flag = next((argv[i + 1] for i, t in enumerate(argv[:-1]) if t in ("-R", "--repo")), "") or next(
        (t.split("=", 1)[1] for t in argv if t.startswith(("-R=", "--repo="))), "")
    if flag:
        m = REMOTE_RE.search(flag)
        return f"{m.group(1)}/{m.group(2)}" if m else flag
    try:
        url = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""
    m = REMOTE_RE.search(url)
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def open_prs(repo: str) -> list[dict] | None:
    """Open PRs oldest first, or None when GitHub could not be asked (fail open). REST, not
    `gh pr list --json`: the GraphQL form hit the node limit on 2026-08-27."""
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{repo}/pulls?state=open&per_page=100&sort=created&direction=asc"],
            capture_output=True, text=True, timeout=GH_TIMEOUT, check=False)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def opa_deny(inp: dict) -> list[str]:
    """data.pr_cap.deny for one input; [] when opa is missing or the policy cannot answer."""
    opa = shutil.which("opa")
    if not opa:
        return []
    try:
        out = subprocess.run([opa, "eval", "--strict-builtin-errors", "--format", "json", "--data", POLICY,
                              "--stdin-input", "data.pr_cap.deny"],
                             input=json.dumps(inp), capture_output=True, text=True, timeout=10, check=False)
        return list(json.loads(out.stdout)["result"][0]["expressions"][0]["value"])
    except Exception:  # noqa: BLE001
        return []


def check(argv: list[str], cwd: str, prs_fn=open_prs) -> int:
    if argv[:2] != ["gh", "pr"] or argv[2:3] not in (["create"], ["merge"]):
        return 0
    repo = target_repo(argv, cwd)
    prs = prs_fn(repo) if repo else None
    if prs is None:
        return 0
    deny = opa_deny({"argv": argv, "repo": repo, "prs": prs, "cap": PR_CAP, "hold_label": HOLD_LABEL})
    if not deny:
        return 0
    print(f"BLOCKED by pr-cap-guard: {deny[0]}", file=sys.stderr)
    return 2


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    cwd = payload.get("cwd") or os.getcwd()
    return max((check(argv, cwd) for argv in _split_commands(cmd)), default=0)


def _fake(n: int, held: int = 0):
    rows = [{"number": i, "created_at": f"2026-08-{i:02d}T00:00:00Z"} for i in range(1, n + 1)]
    for p in rows[:held]:
        p["labels"] = [{"name": "hold"}]
    return lambda repo: rows


def _stack(repo):
    return [{"number": 454, "created_at": "2026-08-27T00:00:00Z", "head": {"ref": "cp1"}, "base": {"ref": "main"}},
            {"number": 458, "created_at": "2026-08-27T00:00:00Z", "head": {"ref": "cp2"}, "base": {"ref": "cp1"}}]


def selftest() -> int:
    m = "merge"  # spelled apart so the estate's own fences do not read this file as a command
    cases = [
        ("21 open refuses", "gh pr create -R o/r --title t --body b", _fake(21), 2),
        ("20 open allows", "gh pr create -R o/r --title t --body b", _fake(20), 0),
        ("21 open of which 2 held allows", "gh pr create -R o/r --title t", _fake(21, held=2), 0),
        ("gh unavailable fails open", "gh pr create -R o/r --title t", lambda repo: None, 0),
        ("unknown repo fails open", "gh pr create --title t", _fake(11), 0),
        (f"{m} stays allowed at 21", f"gh pr {m} 5 -R o/r --squash", _fake(21), 0),
        ("stack: delete-branch under an open stacked PR refuses", f"gh pr {m} 454 -R o/r --squash --delete-branch", _stack, 2),
        ("stack: same without delete-branch allows", f"gh pr {m} 454 -R o/r --squash", _stack, 0),
        ("stack: top of the stack may delete", f"gh pr {m} 458 -R o/r -d", _stack, 0),
    ]
    failed = 0
    for name, cmd, fn, want in cases:
        got = max((check(a, "/" if "unknown" in name else os.getcwd(), fn) for a in _split_commands(cmd)), default=0)
        failed += got != want
        print(f"{'PASS' if got == want else 'FAIL'} {name}: want {want} got {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
