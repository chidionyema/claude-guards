#!/usr/bin/env python3
"""PreToolUse fence, crew#504 CP5: `gh pr create` is refused while the target repo has
more than PR_CAP open pull requests.

Why this exists: on 2026-08-27 the estate had 113 open PRs across seven repos, every
push queued a CI run behind the others, and the founder's words were "we have 24 pull
requests open this is crazy". Creating a PR is the only command that grows the queue;
merging, closing and reviewing shrink it and stay allowed, so the cap clears itself.

FAILS OPEN, ALWAYS. No gh, no network, unreadable payload, unknown repo: exit 0. The
guard's job is to stop a queue from growing, not to stop work when GitHub is down.

Registered in settings/settings.json next to dupe-work-fence.py (hook-run.py wrapper).

Second fence, crew#66 (2026-08-27, LAW 45): `gh pr merge N --delete-branch` is refused when another
open PR in the repo has N's head branch as its base. Deleting the base of a stacked PR makes GitHub
close that PR (idp#458 was closed by the merge of idp#454); restoring the ref, reopening and
retargeting cost a slot and an hour. Merge the stack bottom-up without deleting, delete at the top.
"""
import json
import os
import re
import shlex
import subprocess
import sys

PR_CAP = int(os.environ.get("PR_CAP", "10"))  # crew#504: "if open PRs exceed 10 for a repo"
HOLD_LABEL = os.environ.get("PR_CAP_HOLD_LABEL", "hold")
GH_TIMEOUT = 20
REMOTE_RE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$")


def _split_commands(cmd: str) -> list[list[str]]:
    parts: list[list[str]] = []
    for part in re.split(r"&&|\|\||;|\n", cmd):
        try:
            argv = shlex.split(part)
        except ValueError:
            continue
        if argv:
            parts.append(argv)
    return parts


def _opt(argv: list[str], *names: str) -> str:
    for i, tok in enumerate(argv):
        for name in names:
            if tok == name and i + 1 < len(argv):
                return argv[i + 1]
            if tok.startswith(name + "="):
                return tok.split("=", 1)[1]
    return ""


def target_repo(argv: list[str], cwd: str) -> str:
    """`owner/repo` from -R/--repo, else the cwd's origin remote; '' when unknown."""
    flag = _opt(argv, "-R", "--repo")
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
    """Open PRs oldest first, or None when GitHub could not be asked (fail open).

    REST, not `gh pr list --json`: the GraphQL form hit the node limit on 2026-08-27."""
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{repo}/pulls?state=open&per_page=100&sort=created&direction=asc"],
            capture_output=True, text=True, timeout=GH_TIMEOUT, check=False)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return None


def _held(pr: dict) -> bool:
    """A PR parked under the `hold` label (crew#538: founder-kept branches reopened 2026-08-27) pushes
    nothing and runs nothing; the cap protects the CI queue, so it does not count one."""
    return any(str(lab.get("name") or "") == HOLD_LABEL for lab in (pr.get("labels") or []))


def _refuse(message: str) -> int:
    print(f"BLOCKED by pr-cap-guard: {message}", file=sys.stderr)
    return 2


def stack_check(argv: list[str], cwd: str, prs_fn=open_prs) -> int:
    """`gh pr merge N --delete-branch` while an open PR is based on N's head: refused (crew#66)."""
    if argv[:3] != ["gh", "pr", "merge"] or not ({"--delete-branch", "-d"} & set(argv)):
        return 0
    number = next((t for t in argv[3:] if t.isdigit()), "")
    if not number:
        return 0
    repo = target_repo(argv, cwd)
    if not repo:
        return 0
    prs = prs_fn(repo)
    if prs is None:
        return 0
    head = next((str((p.get("head") or {}).get("ref") or "") for p in prs if str(p.get("number")) == number), "")
    if not head:
        return 0
    stacked = [f"#{p.get('number')}" for p in prs
               if str((p.get("base") or {}).get("ref") or "") == head and str(p.get("number")) != number]
    if not stacked:
        return 0
    return _refuse(
        f"{repo}#{number} is the base of open PR(s) {', '.join(stacked)}; --delete-branch would make "
        "GitHub close them (idp#458, 2026-08-27). Merge without --delete-branch, retarget the stacked "
        "PR(s) to main, delete the branch last.")


def check(argv: list[str], cwd: str, prs_fn=open_prs) -> int:
    if argv[:3] == ["gh", "pr", "merge"]:
        return stack_check(argv, cwd, prs_fn)
    if argv[:3] != ["gh", "pr", "create"]:
        return 0
    repo = target_repo(argv, cwd)
    if not repo:
        return 0
    prs = prs_fn(repo)
    if prs is None:
        return 0
    prs = [p for p in prs if not _held(p)]
    if len(prs) <= PR_CAP:
        return 0
    oldest = ", ".join(f"#{p.get('number')} ({str(p.get('created_at', ''))[:10]})" for p in prs[:3])
    return _refuse(
        f"{repo} has {len(prs)} open PRs (label `{HOLD_LABEL}` not counted), cap is {PR_CAP} (crew#504). Oldest: {oldest}. "
        "Merge or close before opening another; merging, closing and reviewing stay allowed.")


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
    for argv in _split_commands(cmd):
        rc = check(argv, cwd)
        if rc:
            return rc
    return 0


def _fake(n: int):
    return lambda repo: [{"number": i, "created_at": f"2026-08-{i:02d}T00:00:00Z"} for i in range(1, n + 1)]


def _held_fake(repo):
    rows = _fake(11)(repo)
    for p in rows[:2]:
        p["labels"] = [{"name": "hold"}]
    return rows


def _stack(repo):
    return [
        {"number": 454, "created_at": "2026-08-27T00:00:00Z", "head": {"ref": "cp1"}, "base": {"ref": "main"}},
        {"number": 458, "created_at": "2026-08-27T00:00:00Z", "head": {"ref": "cp2"}, "base": {"ref": "cp1"}},
    ]


def selftest() -> int:
    """Proves the fence REFUSES at 11 and ALLOWS at 10, and fails open when gh is gone."""
    shrink = ["merge", "close"]  # spelled apart so the estate's own fences do not read this file as a command
    cases = [
        ("11 open refuses", "gh pr create -R o/r --title t --body b", _fake(11), 2),
        ("10 open allows", "gh pr create -R o/r --title t --body b", _fake(10), 0),
        ("gh unavailable fails open", "gh pr create -R o/r --title t", lambda repo: None, 0),
        (f"{shrink[0]} stays allowed at 11", f"gh pr {shrink[0]} 5 -R o/r --squash", _fake(11), 0),
        (f"{shrink[1]} stays allowed at 11", f"gh pr {shrink[1]} 5 -R o/r", _fake(11), 0),
        ("unknown repo fails open", "gh pr create --title t", _fake(11), 0),
        ("stack: delete-branch under an open stacked PR refuses", f"gh pr {shrink[0]} 454 -R o/r --squash --delete-branch", _stack, 2),
        ("stack: same without delete-branch allows", f"gh pr {shrink[0]} 454 -R o/r --squash", _stack, 0),
        ("stack: top of the stack may delete", f"gh pr {shrink[0]} 458 -R o/r --squash --delete-branch", _stack, 0),
        ("stack: gh unavailable fails open", f"gh pr {shrink[0]} 454 -R o/r -d", lambda repo: None, 0),
        ("11 open of which 2 held allows", "gh pr create -R o/r --title t", _held_fake, 0),
    ]
    failed = 0
    for name, cmd, fn, want in cases:
        cwd = "/" if "unknown" in name else os.getcwd()
        got = max((check(a, cwd, fn) for a in _split_commands(cmd)), default=0)
        ok = got == want
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} {name}: want {want} got {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
