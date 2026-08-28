#!/usr/bin/env python3
"""Refuse a `git merge <target>` call if the target has diverged wildly from
HEAD, the exact class of mistake behind the fork/main incident (2026-08-27):
merged a one-file fix branch into fork/main, which turned out to be 1200+
commits and 5011 files ahead of the branch's own base -- the working tree
was blown apart before the mistake was caught.

WHY. A merge target that "sounds like" a small sibling branch (main, a
feature branch) can silently be a fast-moving mainline that diverged from
your actual base long ago. `git merge` gives no warning; it just does it.

USE: before calling `git merge <target>`, run this first:
    python3 merge-target-divergence-guard.py <target>
Exit 0: safe, proceed. Exit 1: refuse, print the real numbers, ask first.

Threshold: >50 files changed OR >100 commits distance is refused. Both
numbers come from `git diff --stat` / `git rev-list --count`, real
measurements, not a guess.
"""
import subprocess
import sys

MAX_FILES = 50
MAX_COMMITS = 100


def run(cmd: list[str], cwd: str | None = None) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15, cwd=cwd).stdout.strip()


def own_default_branch(target: str, cwd: str | None = None) -> str:
    """'origin/main' when origin is the remote HEAD pushes to and main is that remote's
    default branch: the distance to it is how busy main was, never a wrong sibling.
    2026-08-28: refused a merge of origin/main into a two-hour-old idp branch at 18 commits /
    56 files, while the pre-push hook refuses a branch behind main -- two guards, no path.
    Returns '' for anything else (fork/main, a peer branch, a bare sha)."""
    if "/" not in target:
        return ""
    remote, _, branch = target.partition("/")
    default = run(["git", "symbolic-ref", "-q", "--short", f"refs/remotes/{remote}/HEAD"], cwd=cwd)
    if not default:
        # a worktree or a fetch-only clone never sets refs/remotes/<remote>/HEAD (this idp
        # worktree, 2026-08-28); main/master that the remote really has is the default then
        if branch in ("main", "master") and run(["git", "rev-parse", "--verify", "-q", f"refs/remotes/{remote}/{branch}"], cwd=cwd):
            default = target
    if default != target:
        return ""
    head = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    push_remote = (
        run(["git", "config", "--get", "remote.pushDefault"], cwd=cwd)
        or run(["git", "config", "--get", f"branch.{head}.remote"], cwd=cwd)
        or ("origin" if run(["git", "remote", "get-url", "origin"], cwd=cwd) else "")
    )
    if push_remote != remote:
        return ""
    return f"the default branch ({branch}) of your own remote {remote}"


def check(target: str, cwd: str | None = None) -> tuple[bool, str]:
    """Returns (safe, message)."""
    own = own_default_branch(target, cwd)
    if own:
        return True, f"OK: '{target}' is {own} -- refreshing on your own main is LAW 7, not a sibling merge"
    merge_base = run(["git", "merge-base", "HEAD", target], cwd=cwd)
    if not merge_base:
        return False, f"REFUSE: no merge-base found between HEAD and '{target}' -- unrelated histories, do not merge blind"

    files = run(["git", "diff", "--stat", merge_base, target], cwd=cwd).splitlines()
    # last line of --stat is the summary "N files changed, ..."
    file_count = 0
    for line in files:
        if "file" in line and "changed" in line:
            try:
                file_count = int(line.strip().split()[0])
            except (ValueError, IndexError):
                pass

    commit_count_out = run(["git", "rev-list", "--count", f"{merge_base}..{target}"], cwd=cwd)
    commit_count = int(commit_count_out) if commit_count_out.isdigit() else 0

    if file_count > MAX_FILES or commit_count > MAX_COMMITS:
        return False, (
            f"REFUSE: '{target}' has diverged {commit_count} commits / {file_count} files "
            f"from your merge-base with HEAD (thresholds: {MAX_COMMITS} commits / {MAX_FILES} files). "
            f"This is very likely NOT the sibling branch you think it is -- "
            f"check with crew / the repo owner before merging into it."
        )
    return True, f"OK: '{target}' is {commit_count} commits / {file_count} files from merge-base -- safe to merge"


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        return selftest()
    if len(sys.argv) != 2:
        print("usage: merge-target-divergence-guard.py <merge-target-ref>", file=sys.stderr)
        return 2
    safe, msg = check(sys.argv[1])
    print(msg)
    return 0 if safe else 1


def selftest() -> int:
    # Pure-logic test: the real incident's actual numbers (fork/main: 1201 commits,
    # 5011 files ahead of merge-base -- from this session's real `git status --short
    # | wc -l` and `git rev-list --count` output) fed straight into the threshold
    # check, no real git subprocess needed. Isolates the guard's own arithmetic from
    # git's behavior, which is what actually matters here.
    import unittest.mock as mock

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["git", "merge-base"]:
            return "deadbeef"
        if cmd[:2] == ["git", "diff"]:
            return "5011 files changed, 900000 insertions(+), 1 deletion(-)"
        if cmd[:2] == ["git", "rev-list"]:
            return "1201"
        return ""

    with mock.patch("__main__.run", side_effect=fake_run):
        safe, msg = check("fork/main")
    ok1 = not safe

    def fake_run_own(cmd, cwd=None):
        if cmd[:2] == ["git", "symbolic-ref"]:
            return "origin/main"
        if cmd[:3] == ["git", "config", "--get"] and cmd[3] == "remote.pushDefault":
            return "origin"
        return fake_run(cmd, cwd)

    with mock.patch("__main__.run", side_effect=fake_run_own):
        safe, msg = check("origin/main")
    ok_own = safe
    print("own origin/main at incident numbers:", "OK permitted" if ok_own else "FAIL refused own main", "--", msg[:100])

    with mock.patch("__main__.run", side_effect=fake_run_own):
        safe, msg = check("fork/main")
    ok_fork = not safe
    print("fork/main still refused with the exemption in place:", "REFUSE ok" if ok_fork else "FAIL", "--", msg[:80])
    print("bad (real incident numbers):", "REFUSE ok" if ok1 else "FAIL should have refused", "--", msg[:100])

    def fake_run_small(cmd, cwd=None):
        if cmd[:2] == ["git", "merge-base"]:
            return "deadbeef"
        if cmd[:2] == ["git", "diff"]:
            return "1 file changed, 3 insertions(+), 1 deletion(-)"
        if cmd[:2] == ["git", "rev-list"]:
            return "1"
        return ""

    with mock.patch("__main__.run", side_effect=fake_run_small):
        safe2, msg2 = check("origin/sibling-branch")
    ok2 = safe2
    print("good (small diff):", "PASS ok" if ok2 else "FAIL should have passed", "--", msg2[:80])

    return 0 if (ok1 and ok2 and ok_own and ok_fork) else 1


if __name__ == "__main__":
    raise SystemExit(main())
