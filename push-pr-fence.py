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
pull requests sat open and nothing merged. `.github/workflows/automerge.yml` merged a PR the
moment its CI run concluded `success`, so a CANCELLED run merged nothing, ever.

THAT WORKFLOW NO LONGER EXISTS, AND EVERY MESSAGE BELOW USED TO PROMISE IT WOULD ACT. It was
deleted from main in #522 -- deliberately, on the founder's directive "i only want to see one pr
as they should be merged into a single branch and closed off". Two angles measured 2026-08-20:
`git cat-file -e origin/main:.github/workflows/automerge.yml` reports absent, and #524 through
#528 were every one of them `mergedBy=chidionyema`, by hand. NOTHING MERGES A GREEN PULL REQUEST
FOR YOU. A session that pushes, goes green and waits, waits forever -- which is how #528's
successor sat stranded for half an hour on 2026-08-20 while its author watched a run that had
already passed. When your run concludes green, YOU merge it:

    gh pr merge <n> --merge

Main is still protected: `main-admission-guard` reverts a merge with no green run at its head.

Back in 2026-08-19, `.github/workflows/ci.yml` also set `cancel-in-progress` for every ref that
was not main, so ANY push to a PR branch killed that branch's in-flight run.

THAT CAUSE IS FIXED AND THE FENCE IS STILL RIGHT. Measured 2026-08-20 on main, ci.yml:123-125 is
now `group: ci-${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: false`, and
that is the only such setting in the file -- a push no longer kills anything. What it does
instead is QUEUE: GitHub holds at most one pending run per group, so the new run waits out the
full length of a run that is grading a sha which is no longer the branch head. The python job
takes about 25 minutes. A branch touched more often than that still never produces a completed
run at its current head; the waste simply moved from a cancellation to a queue.

Do not read this refusal as evidence that cancel-in-progress needs fixing. It was fixed. Check
before you act on it: `gh api "repos/OWNER/REPO/contents/.github/workflows/ci.yml?ref=main"`.

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


def follow_cd(cwd: str, target: str) -> str:
    """Where a `cd` earlier in the SAME command block leaves the shell.

    The hook is handed the SESSION's cwd. Agents on this estate write
    `cd <worktree> && git push`, so the push runs in a different repository than the one the hook
    was told about. Measured 2026-08-20: this fence read the iCloud checkout, 113 commits behind
    main, and refused a push from a worktree that was 0 behind. It printed a real number about the
    wrong tree, so the refusal read as correct and there was no tell from the outside.

    An unreadable directory leaves the cwd alone, which is what the fence did before this existed.
    """
    target = os.path.expanduser(target)
    path = target if os.path.isabs(target) else os.path.join(cwd, target)
    return os.path.normpath(path) if os.path.isdir(path) else cwd


def git_c_dir(argv: list[str], cwd: str) -> str:
    """`git -C <dir> push` runs in <dir> whatever the shell cwd is. Same trap as `cd`."""
    for i, a in enumerate(argv):
        if a == "-C" and i + 1 < len(argv):
            return follow_cd(cwd, argv[i + 1])
    return cwd


def commits_behind_main(cwd: str) -> int | None:
    """How many commits origin/main has that this branch does not. None when it cannot tell.

    The REMOTE is asked, not the local `origin/main` ref. A local ref that has not been fetched
    today reports 0 while the branch is a day stale, which is the exact failure this check exists
    to catch.
    """
    if run("git", "fetch", "origin", "main", "--quiet", cwd=cwd)[0] != 0:
        return None
    c, out = run("git", "rev-list", "--count", "HEAD..FETCH_HEAD", cwd=cwd)
    if c != 0 or not out.isdigit():
        return None
    return int(out)


def merged_into_main(tip: str, cwd: str) -> bool:
    """True when a remote branch tip is already an ANCESTOR of origin/main.

    Such a branch is the leftover ref of a cycle that has merged. Every commit on it is in the
    trunk, so it hides nothing, and no pull request can be opened on it at all -- GitHub answers
    "No commits between main and <branch>". This fence exists to stop commits piling up where
    nobody can see them. There is nothing here to see.

    Measured 2026-08-20: origin/integrate/2026-08-20-final sat at 633ead53, an ancestor of
    origin/main at 6e335462, and ~/.claude/PR_FREEZE named that branch as the single head any
    session was allowed to propose. So no push could happen without an open review, no review
    could be opened without commits, and no commits could arrive without a push. Zero reviews
    were open, which left no branch in the estate anyone could legally ship on. Both guards were
    behaving exactly as written; the deadlock was in the pair.

    This is the one check in the file that fails CLOSED. Every other unknown here fails open,
    because a fence that blocks when it cannot see is worse than the problem it solves. Not this
    one: a missing object or an unreachable remote answers False and the fence stays up, since
    failing open on ancestry would wave through every push the fence exists to refuse.
    """
    if not tip:
        return False
    c, out = run("git", "ls-remote", "--heads", "origin", "main", cwd=cwd)
    if c != 0 or not out.split():
        return False
    trunk = out.split()[0]
    if tip == trunk:
        return True
    c, _ = run("git", "merge-base", "--is-ancestor", tip, trunk, cwd=cwd)
    return c == 0


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


def git_subcommand(argv: list[str]) -> str | None:
    """The git SUBCOMMAND, with git's own global options skipped.

    WHY (measured 2026-08-21, and it blocked a real command). The test used to be
    `"push" not in argv[:4]`, which is true of `git stash push`, `git subtree push` and
    `git commit -m "...push..."`. A `git stash push -m "<message>"` was refused by this fence,
    which then parsed the STASH MESSAGE as a branch name and reported it "5 commits behind
    origin/main". A guard that refuses an unrelated command teaches sessions to work around
    the guard, which is how a fence gets uninstalled.

    Global options come BEFORE the subcommand and some of them take a value, so a value has to
    be consumed with its flag or the next word is mistaken for the subcommand.
    """
    takes_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
    i = 1
    while i < len(argv):
        a = argv[i]
        if not a.startswith("-"):
            return a
        if a in takes_value:
            i += 2
            continue
        i += 1
    return None


def selftest_staleness() -> tuple[list[str], int]:
    """Prove `commits_behind_main` reports the three answers that decide the LAW 7 block.

    Offline: `origin` is a local directory, so `git fetch` is a file copy and no network is
    touched. A check that only ever returns the allow answer is not a check, so the stale case
    is built on purpose and asserted to be non-zero.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    def git(*a: str, cwd: str) -> None:
        subprocess.run(("git",) + a, cwd=cwd, capture_output=True, check=True)

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        origin, clone = str(Path(tmp) / "origin"), str(Path(tmp) / "clone")
        Path(origin).mkdir()
        git("init", "--initial-branch", "main", "-q", cwd=origin)
        git("config", "user.email", "t@t", cwd=origin)
        git("config", "user.name", "t", cwd=origin)
        (Path(origin) / "a").write_text("1")
        git("add", "a", cwd=origin)
        git("commit", "-qm", "one", cwd=origin)
        subprocess.run(("git", "clone", "-q", origin, clone), capture_output=True, check=True)
        git("config", "user.email", "t@t", cwd=clone)
        git("config", "user.name", "t", cwd=clone)
        git("checkout", "-qb", "work", cwd=clone)

        if commits_behind_main(clone) != 0:
            failures.append("  fresh branch: want 0 behind, "
                            f"got {commits_behind_main(clone)!r}")

        # main moves twice while the branch sits still -- the case the block exists to refuse.
        for n in ("2", "3"):
            (Path(origin) / "a").write_text(n)
            git("commit", "-qam", n, cwd=origin)
        if commits_behind_main(clone) != 2:
            failures.append("  stale branch: want 2 behind, "
                            f"got {commits_behind_main(clone)!r}")

        # ...and merging main is what clears it. This is the escape the message tells you to use.
        git("fetch", "origin", "main", "-q", cwd=clone)
        git("merge", "FETCH_HEAD", "-q", "--no-edit", cwd=clone)
        if commits_behind_main(clone) != 0:
            failures.append("  after merging main: want 0 behind, "
                            f"got {commits_behind_main(clone)!r}")

    with tempfile.TemporaryDirectory() as empty:
        if commits_behind_main(empty) is not None:
            failures.append("  not a git repo: want None so the fence fails OPEN, "
                            f"got {commits_behind_main(empty)!r}")

    return failures, 4


def selftest_merged_exemption() -> tuple[list[str], int]:
    """Prove `merged_into_main` says yes to a merged leftover and no to everything else.

    Offline: `origin` is a local directory, so `ls-remote` is a file read and no network is
    touched. The refusing cases are the ones that matter. An exemption that answered True for a
    branch carrying its own commits would not be an exemption, it would be the end of the fence,
    so the unmerged case and the unknown-object case are both built on purpose and asserted.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    def git(*a: str, cwd: str) -> str:
        p = subprocess.run(("git",) + a, cwd=cwd, capture_output=True, text=True, check=True)
        return p.stdout.strip()

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        origin, clone = str(Path(tmp) / "origin"), str(Path(tmp) / "clone")
        Path(origin).mkdir()
        git("init", "--initial-branch", "main", "-q", cwd=origin)
        git("config", "user.email", "t@t", cwd=origin)
        git("config", "user.name", "t", cwd=origin)
        (Path(origin) / "a").write_text("1")
        git("add", "a", cwd=origin)
        git("commit", "-qm", "one", cwd=origin)
        old = git("rev-parse", "HEAD", cwd=origin)
        subprocess.run(("git", "clone", "-q", origin, clone), capture_output=True, check=True)

        # main tip itself: the branch and the trunk are the same commit.
        if not merged_into_main(old, clone):
            failures.append("  tip == main: want exempt, got refused")

        # main moves on. `old` is now a strict ancestor -- the leftover ref of a merged cycle,
        # which is the whole case this exemption exists for. But the clone has not fetched, so
        # main's new tip is a sha it holds no object for and the ancestry cannot be computed.
        # That answers REFUSED, and this case is here to pin that it does: the check must not
        # guess when it cannot see. In practice LAW 7 has already made the caller fetch, since
        # a branch behind main is blocked earlier by commits_behind_main.
        (Path(origin) / "a").write_text("2")
        git("commit", "-qam", "two", cwd=origin)
        if merged_into_main(old, clone):
            failures.append("  ancestor, trunk object absent: want REFUSED, got exempt")

        # Now fetch, which is what a caller obeying LAW 7 has already done. The object is
        # present, the ancestry resolves, and the leftover ref is exempt.
        git("fetch", "-q", "origin", cwd=clone)
        if not merged_into_main(old, clone):
            failures.append("  ancestor of main: want exempt, got refused")

        # A branch carrying a commit main does not have. This one must STILL be fenced, or the
        # exemption has quietly disabled the guard.
        git("checkout", "-qb", "work", cwd=clone)
        (Path(clone) / "b").write_text("x")
        git("add", "b", cwd=clone)
        git("commit", "-qm", "unique", cwd=clone)
        mine = git("rev-parse", "HEAD", cwd=clone)
        if merged_into_main(mine, clone):
            failures.append("  branch with its own commit: want REFUSED, got exempt")

        # Fails closed: a sha this repo has never seen cannot be graded, so it is not exempt.
        if merged_into_main("0" * 40, clone):
            failures.append("  unknown object: want REFUSED, got exempt")
        if merged_into_main("", clone):
            failures.append("  empty tip: want REFUSED, got exempt")

    return failures, 5


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

    staleness_failures, staleness_total = selftest_staleness()
    failures += staleness_failures

    merged_failures, merged_total = selftest_merged_exemption()
    failures += merged_failures

    # The fence must fire on a push and ONLY on a push. Each of these was a real refusal or a
    # real hole: `git stash push -m` was blocked and its message read as a branch name.
    for argv, want, why in [
        (["git", "push", "origin", "b"], "push", "a plain push is a push"),
        (["git", "-C", "/tmp/x", "push", "origin", "b"], "push", "-C takes a value"),
        (["git", "-c", "user.name=x", "push"], "push", "-c takes a value"),
        (["git", "--no-pager", "push"], "push", "a valueless global option is skipped"),
        (["git", "stash", "push", "-m", "note"], "stash", "git stash push is NOT a push"),
        (["git", "subtree", "push", "--prefix", "x"], "subtree", "nor is subtree push"),
        (["git", "commit", "-m", "push the fix"], "commit", "nor is the word in a message"),
        (["git"], None, "bare git has no subcommand"),
    ]:
        got = git_subcommand(argv)
        if got != want:
            failures.append(f"  git_subcommand({argv}): want {want!r}, got {got!r} -- {why}")

    total = len(SELFTEST_CASES) + 6 + staleness_total + merged_total + 8
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
        if argv[:1] == ["cd"] and len(argv) > 1:
            cwd = follow_cd(cwd, argv[1])
            continue
        if len(argv) < 2 or argv[0] != "git" or git_subcommand(argv) != "push":
            continue
        cwd = git_c_dir(argv, cwd)
        if any(a in ("--delete", "-d", "--dry-run", "--tags") for a in argv):
            continue
        if any(a.startswith(":") or ":refs/heads/" in a and a.startswith(":") for a in argv):
            continue

        branch = target_branch(argv, cwd)
        if not branch or branch == "main" or branch.startswith(EXEMPT_PREFIXES):
            continue

        # LAW 7 -- refresh on main before you ask for review. A branch behind main is graded
        # against a world that no longer exists, so its gate fails naming files and tests that
        # have nothing to do with the change. Measured 2026-08-20: five failures on one branch,
        # three of them in a test file main had already deleted.
        if not os.environ.get("PUSH_ANYWAY"):
            behind = commits_behind_main(cwd)      # None => cannot tell => fail open
            if behind:
                print(f"BLOCKED by push-pr-fence: `{branch}` is {behind} commit(s) behind "
                      f"origin/main.\n"
                      f"LAW 7 -- refresh on main before you ask for review. Its gate would grade "
                      f"your code against a main that has moved, and the red it prints would name "
                      f"files your change never touched.\n"
                      f"  git merge origin/main --no-edit\n"
                      f"Merge it. NEVER rebase and force push: the remote moves by itself here, "
                      f"so a force push destroys work you never saw arrive.\n"
                      f"If this genuinely cannot wait: PUSH_ANYWAY=1 git push ...",
                      file=sys.stderr)
                return 2

        # First push of a branch is how it comes into existence -- always allowed.
        c, out = run("git", "ls-remote", "--heads", "origin", branch, cwd=cwd)
        if c != 0:
            return 0                       # cannot reach the remote: fail open
        if not out:
            continue                        # branch is not on origin yet

        # The ref is on origin but every commit on it is already in main: a merged cycle's
        # leftover. Nothing can be opened on it -- GitHub answers "No commits between" -- so
        # demanding a review first is a demand that cannot be met. This is the same reasoning the
        # fence already applies to a first push, for a branch that outlived its own merge, and it
        # is the ordinary shape rather than a rare one: a merge leaves the ref behind, so every
        # branch looks like this the moment it lands -- once per merge cycle, not once per
        # firefight. That was true of automerge.yml and it is still true of the hand merges that
        # replaced it. See merged_into_main.
        #
        # KNOWN HOLE, and it is why the check below exists in the reader's head rather than here.
        # `out` is the branch's CURRENT REMOTE TIP, which seconds after a merge is by definition
        # an ancestor of main -- so this exemption fires and the open-PR check below is never
        # reached. It grades the ref you are pushing ONTO, not the commits you are pushing. The
        # obvious repair re-creates the deadlock this exemption exists for, and no PreToolUse hook
        # can fix it: the push is a PRECONDITION of opening the PR, so nothing running before the
        # push can repair the state. Measured, so nobody re-derives it: `rev-list --count
        # origin/main..<remote tip>` is 0 in BOTH the deadlock case and the just-merged case, so
        # it cannot split them either. AFTER ANY PUSH ONTO A BRANCH THAT HAS JUST MERGED, CHECK:
        #     gh pr list --head <branch> --state open
        # Empty means your work is invisible and nothing will merge it. Open one.
        if merged_into_main(out.split()[0], cwd):
            continue

        c, out = run("gh", "pr", "list", "--head", branch, "--state", "open",
                     "--json", "number", cwd=cwd)
        if c != 0:
            return 0                       # gh unavailable or unauthenticated: fail open
        try:
            if json.loads(out or "[]"):
                # A pull request is open, so the work is visible. One thing left to check:
                # a second run would QUEUE behind this one rather than replace it, so pushing now
                # buys nothing and costs the queue.
                live = live_ci_run(branch, cwd)
                if live is None:
                    continue                # cannot tell: fail open
                if not live:
                    continue                # nothing running: push away
                rid, status = live
                print(
                    f"BLOCKED by push-pr-fence: CI run {rid} for `{branch}` is {status}.\n"
                    f"Pushing does not cancel it any more -- ci.yml is `cancel-in-progress: "
                    f"false` on main as of 2026-08-20, so do NOT go and 'fix' that. Your run "
                    f"would QUEUE instead: GitHub holds one pending run per group, so it waits "
                    f"out the whole of a run that is grading a sha you have already replaced. "
                    f"The python job is about 25 minutes.\n"
                    f"NOTHING MERGES IT WHEN IT GOES GREEN. automerge.yml was deleted from "
                    f"main in #522; every merge since has been by hand. When the run concludes "
                    f"green, run `gh pr merge <n> --merge` yourself.\n\n"
                    f"Watch it, then push when it lands:\n"
                    f"  gh run watch {rid}\n"
                    f"  gh run list --branch {branch} --limit 1\n\n"
                    f"BEFORE YOU WAIT: check whether the sha it is grading still contains what "
                    f"failed last time. A run grading a commit that carries the known-fatal line "
                    f"cannot go green, and waiting it out costs 25 minutes for a red:\n"
                    f"  git show <that sha>:<the file> | grep '<the failing line>'\n"
                    f"If it does, this is exactly the case for: PUSH_ANYWAY=1 git push ...\n"
                    f"Otherwise, if the run is stuck or this genuinely cannot wait, same escape.",
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
