#!/usr/bin/env python3
"""Refuse to push a branch that already exists on origin and has no pull request.

WHY THIS EXISTS AND WHY THE OLD GUARD WAS NOT ENOUGH.

`branch-pr-guard.py` is a Stop hook. It fires after the push has already happened, once per
commit, and the session answers "deliberately not for review" and carries on. On 2026-08-18 the
founder found remote branches two weeks old that had been pushed to repeatedly with no pull
request, while that guard was installed and firing. A hook that reports after the fact is a nag.
This one sits on the push itself.

THE RULE.

  first push of a branch      allowed. This is how a branch gets created, and the PR cannot be
                              opened before the branch exists on the remote.
  later pushes, PR open       allowed. The work is visible; that was the whole point.
  later pushes, no PR         REFUSED. Open the pull request, then push again.
  push while its CI is live   REFUSED. See below.

THE SECOND RULE: DO NOT CANCEL THE RUN THAT WOULD HAVE MERGED IT.

Measured 2026-08-19 across the last 60 CI runs: 7 success, 16 failure, 16 cancelled. Twenty-two
pull requests sat open and nothing merged. `.github/workflows/automerge.yml` merges a PR the
moment its CI run concludes `success`, so a CANCELLED run merges nothing, ever. And
`.github/workflows/ci.yml` sets `cancel-in-progress` for every ref that is not main, so ANY push
to a PR branch kills that branch's in-flight run. The python job takes about 25 minutes. A branch
touched more often than that never produces a completed run.

Several agents share this estate and cannot see each other. Each one independently found "CI is
red", pushed a fix, and cancelled the run that was about to go green -- often a run carrying
another agent's fix. The work was not wrong. It kept resetting the clock.

So a push is refused while a CI run for that branch is queued or in progress. Wait for it. If the
run is genuinely stuck, or the push must go now, set PUSH_ANYWAY=1 in the environment.

So a branch may exist without a PR for exactly as long as it takes to open one, and no longer.
Accumulating commits on an invisible branch is what stops being possible.

NEVER FENCED.

  main                        the shared trunk
  archive/ backup/ rescue/    safety copies whose entire purpose is to hold work that is NOT
  salvage/ parked/ capture/   proposed for review. Requiring a PR for them would be nonsense.
  --delete / :refs/heads/     deleting a remote branch is cleanup, not hidden work
  --dry-run                   changes nothing

FAILING OPEN.

If `gh` is missing, unauthenticated, or the network is down, the PR state cannot be established
and the push is ALLOWED. A fence that blocks work when it cannot see is worse than the problem
it solves; the Stop-hook nag still catches those cases afterwards.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

EXEMPT_PREFIXES = ("archive/", "backup/", "rescue/", "salvage/", "parked/", "capture/")
#: `git push` with no refspec pushes the current branch; these forms name it explicitly.
REFSPEC = re.compile(r"^(?:\+)?(?:HEAD|refs/heads/[^:]+|[^:]+)?:(?:refs/heads/)?(?P<dst>[^:]+)$")


def run(*cmd: str, cwd: str) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return p.returncode, (p.stdout or "").strip()


def target_branch(argv: list[str], cwd: str) -> str | None:
    """The branch name this push would write on the remote, or None if it cannot be determined.

    `git push [remote] [refspec]`. The first bare word after `push` is the REMOTE, not a branch --
    reading it as one made every push look like a push to a branch called `origin`, which has no
    pull request and does not exist on the remote, so the fence passed everything.
    """
    words = [a for a in argv[argv.index("push") + 1:] if not a.startswith("-")]
    if words and ":" not in words[0]:
        words = words[1:]                   # drop the remote
    for a in words:
        m = REFSPEC.match(a)
        if m:
            return m.group("dst")
        if ":" not in a:
            return a
    c, out = run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    return out if c == 0 and out and out != "HEAD" else None


#: (argv, expected branch) for `target_branch`. This is where the fence's one real bug lived:
#: the first bare word after `push` is the REMOTE, and reading it as a branch made every push
#: look like a push to a branch called `origin` -- which has no PR and is not on the remote, so
#: the fence silently passed everything. A parser that fails this way looks identical to one
#: that works, because the hook fails OPEN by design.
SELFTEST_CASES: list[tuple[list[str], str | None]] = [
    (["git", "push", "origin", "my-branch"], "my-branch"),
    (["git", "push", "origin", "HEAD:my-branch"], "my-branch"),
    (["git", "push", "origin", "HEAD:refs/heads/my-branch"], "my-branch"),
    (["git", "push", "origin", "local-name:remote-name"], "remote-name"),
    (["git", "push", "origin", "+feature:feature"], "feature"),
    (["git", "push", "-u", "origin", "my-branch"], "my-branch"),
    (["git", "push", "--force-with-lease", "origin", "my-branch"], "my-branch"),
    (["git", "push", "origin", "archive/old-work"], "archive/old-work"),
    # The remote must never be returned as the branch. `origin` alone falls through to the
    # HEAD lookup, which cannot run in a directory that is not a repository, so: None.
    (["git", "push", "origin"], None),
    (["git", "push"], None),
]


def selftest() -> int:
    """Check the refspec parser against the shapes that were argued about when it was written.

    Only `target_branch` is covered. The rest of the fence asks git and gh about the live
    remote, and a selftest that needed a network round trip would not be run. Graded by
    `scripts/process_audit.py`, so a failure shows on the ops console.
    """
    import tempfile

    failures = []
    with tempfile.TemporaryDirectory() as empty:  # not a git repo: the HEAD fallback returns None
        for argv, want in SELFTEST_CASES:
            got = target_branch(argv, empty)
            if got != want:
                failures.append(f"  {' '.join(argv)}\n    want {want!r}, got {got!r}")

    # The exemption list must stay prefixes, not substrings: a branch called
    # `feat/backup-restore` is ordinary work and must NOT be waved through.
    for name, exempt in (("archive/old", True), ("backup/x", True), ("capture/y", True),
                         ("feat/backup-restore", False), ("main", False), ("fix/archive", False)):
        if name.startswith(EXEMPT_PREFIXES) is not exempt:
            failures.append(f"  exemption {name!r}: want exempt={exempt}")

    total = len(SELFTEST_CASES) + 6
    if failures:
        print(f"push-pr-fence selftest: {len(failures)}/{total} FAILED")
        print("\n".join(failures))
        return 1
    print(f"push-pr-fence selftest: {total}/{total} passed")
    return 0


def live_ci_run(branch: str, cwd: str) -> tuple[str, str] | None | bool:
    """The queued or in-progress CI run for `branch`, if there is one.

    Returns (run id, status) when one is live, False when none is, and None when the answer
    cannot be established -- the caller fails OPEN on None, same as every other unknown here.

    Only ci.yml is consulted. The deploy and drill workflows do not gate a merge, and blocking a
    push on one of those would fence work for a run nothing is waiting on.
    """
    if os.environ.get("PUSH_ANYWAY"):
        return False
    c, out = run("gh", "run", "list", "--workflow", "ci.yml", "--branch", branch,
                 "--limit", "5", "--json", "databaseId,status", cwd=cwd)
    if c != 0:
        return None
    try:
        runs = json.loads(out or "[]")
    except json.JSONDecodeError:
        return None
    for r in runs:
        if r.get("status") in ("queued", "in_progress", "waiting", "requested", "pending"):
            return str(r.get("databaseId")), str(r.get("status"))
    return False


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

    for part in re.split(r"&&|\|\||;|\n", cmd):
        try:
            argv = shlex.split(part)
        except ValueError:
            continue
        if len(argv) < 2 or argv[0] != "git" or "push" not in argv[:3]:
            continue
        if any(a in ("--delete", "-d", "--dry-run", "--tags") for a in argv):
            continue
        if any(a.startswith(":") or ":refs/heads/" in a and a.startswith(":") for a in argv):
            continue

        branch = target_branch(argv, cwd)
        if not branch or branch == "main" or branch.startswith(EXEMPT_PREFIXES):
            continue

        # First push of a branch is how it comes into existence -- always allowed.
        c, out = run("git", "ls-remote", "--heads", "origin", branch, cwd=cwd)
        if c != 0:
            return 0                       # cannot reach the remote: fail open
        if not out:
            continue                        # branch is not on origin yet

        c, out = run("gh", "pr", "list", "--head", branch, "--state", "open",
                     "--json", "number", cwd=cwd)
        if c != 0:
            return 0                       # gh unavailable or unauthenticated: fail open
        try:
            if json.loads(out or "[]"):
                # A pull request is open, so the work is visible. One thing left to check:
                # pushing now would cancel this branch's in-flight CI, and automerge.yml only
                # merges on a run that COMPLETES green.
                live = live_ci_run(branch, cwd)
                if live is None:
                    continue                # cannot tell: fail open
                if not live:
                    continue                # nothing running: push away
                rid, status = live
                print(
                    f"BLOCKED by push-pr-fence: CI run {rid} for `{branch}` is {status}.\n"
                    f"Pushing cancels it (ci.yml sets cancel-in-progress for every ref that is "
                    f"not main), and automerge.yml only merges a PR whose CI run CONCLUDES "
                    f"green. A cancelled run merges nothing.\n"
                    f"Measured 2026-08-19: 7 of the last 60 CI runs succeeded, 16 were "
                    f"cancelled, and 22 PRs sat open with nothing merging.\n\n"
                    f"Watch it, then push when it lands:\n"
                    f"  gh run watch {rid}\n"
                    f"  gh run list --branch {branch} --limit 1\n\n"
                    f"If the run is stuck or this genuinely cannot wait: PUSH_ANYWAY=1 git push ...",
                    file=sys.stderr,
                )
                return 2
        except json.JSONDecodeError:
            return 0

        print(
            f"BLOCKED by push-pr-fence: `{branch}` is already on origin and has no open pull "
            f"request.\n"
            f"A branch may sit on the remote without a PR only for as long as it takes to open "
            f"one. Pushing more commits onto it makes work no one can see, which is how the "
            f"remote reached two-week-old branches nobody could account for.\n\n"
            f"Open it, then push again:\n"
            f"  gh pr create --base main --head {branch} --title ... --body ...\n\n"
            f"If it is deliberately not for review, name it with one of: "
            f"{', '.join(EXEMPT_PREFIXES)}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
