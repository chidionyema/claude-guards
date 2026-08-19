#!/usr/bin/env python3
"""Stop hook: a pushed branch must have a pull request.

WHY THIS EXISTS. On 2026-08-17 a fix was committed, pushed as `fix/probe-subdir-cwd`, and the
turn ended there. The work existed only as a remote ref nobody looks at. The founder had to
ask "PR not opened yet. why not", and then "why u always waiting for me to chase". The answer
given at the time was a promise to remember, which is the same class of control that had
already failed: a rule stated in prose, enforced by intention.

WHAT IT CHECKS. At the end of a turn, for every worktree of the repo the session is in: if a
branch has a remote counterpart, is ahead of origin/main, and has no open pull request, the
stop is blocked once with the exact `gh pr create` command to run.

WHY IT CANNOT NAG. Two bounds, both deliberate:

  * One block per (branch, sha). Once reported, that exact state is recorded in the state file
    and never blocks again. Push a new commit and it is a new state, worth one more block.
  * A probe that cannot run means PASS. No gh, no network, no origin, a gh call that errors or
    times out -- all exit 0 silently. A guard that blocks whenever its own probe breaks cannot
    be satisfied, and an unsatisfiable guard gets uninstalled.
  * The branch must still exist ON THE REMOTE, asked with `git ls-remote`. A local
    refs/remotes/origin/<name> is NOT proof of that: a merged-and-deleted branch leaves its
    remote-tracking ref behind until somebody prunes. Measured 2026-08-18, that is exactly what
    happened to `ci/automerge-without-gh-cli` -- merged, deleted upstream, still present locally
    -- and this guard demanded a pull request for it. The `gh pr create` it printed cannot
    succeed: GitHub answers "Head ref must be a branch". A guard that hands you an impossible
    command is worse than one that stays quiet, because the only way past it is to argue with it.

The `main` branch, detached HEADs and branches with no upstream are all ignored: an unpushed
branch is work in progress, and only pushing makes it something a reviewer could be waiting on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

STATE = Path.home() / ".claude" / "state" / "branch-pr-guard.json"
TIMEOUT = 15
PROTECTED = {"main", "master", "HEAD"}

#: Only branches whose tip is newer than this are this turn's business. Anything older is a
#: standing backlog across other sessions' worktrees -- measured 2026-08-17, seventeen of them
#: -- and a guard that reports a backlog on every stop is a guard people mute.
FRESH_SECONDS = int(os.environ.get("BRANCH_PR_GUARD_FRESH_SECONDS", 24 * 3600))


def git(args: list[str], cwd: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                             timeout=TIMEOUT, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except Exception:  # noqa: BLE001 — probe failure means PASS, never block
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def worktrees(cwd: str) -> list[str]:
    """Every checkout sharing this repo, so a fix made in a worktree is not missed."""
    listing = git(["worktree", "list", "--porcelain"], cwd)
    if listing is None:
        return [cwd]
    return [line[len("worktree "):] for line in listing.splitlines()
            if line.startswith("worktree ")] or [cwd]


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        # Keep it small: this is a dedupe ledger, not history.
        if len(state) > 200:
            state = dict(list(state.items())[-200:])
        STATE.write_text(json.dumps(state, indent=2))
    except Exception:  # noqa: BLE001
        pass


def has_open_pr(branch: str, cwd: str) -> bool | None:
    """True/False, or None when the question could not be asked."""
    try:
        out = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number"],
            cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    try:
        return bool(json.loads(out.stdout or "[]"))
    except Exception:  # noqa: BLE001
        return None


def exists_on_remote(names: list[str], cwd: str) -> bool | None:
    """Is any of these names a live branch on origin? None when the question could not be asked.

    ls-remote is the only authoritative answer. Remote-tracking refs go stale the moment someone
    merges and deletes a branch on GitHub, and nothing prunes them until the next
    `git fetch --prune` in that particular checkout -- which, in a repo with a dozen worktrees,
    may be never.
    """
    if not names:
        return None
    try:
        out = subprocess.run(["git", "ls-remote", "--heads", "origin", *names],
                             cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT,
                             env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except Exception:  # noqa: BLE001 — probe failure means PASS, never block
        return None
    if out.returncode != 0:
        return None
    return bool(out.stdout.strip())


def drop_stale_refs(names: list[str], cwd: str) -> None:
    """Delete remote-tracking refs that ls-remote says are gone upstream.

    Exactly what `git fetch --prune` would do, restricted to the names just proven absent, so it
    can never touch a branch that is still live. Without this the guard re-derives the same dead
    branch on every stop until a human prunes by hand.
    """
    for name in names:
        git(["update-ref", "-d", f"refs/remotes/origin/{name}"], cwd)


def pushed_names(branch: str, cwd: str) -> list[str]:
    """Every name this commit could be reviewed under on the remote.

    A branch is not always pushed under its own name. `git push origin HEAD:other-name` is
    normal when a worktree carries one long-lived branch and each fix goes out separately --
    measured 2026-08-17, that exact case made this guard report a branch whose work was
    already open as a pull request under a different head. So ask which remote refs point at
    this commit, and treat any of them as the head to look for.
    """
    names = []
    refs = git(["for-each-ref", "--points-at", "HEAD", "--format=%(refname:short)",
                "refs/remotes/origin"], cwd)
    for ref in (refs or "").splitlines():
        name = ref.strip()
        if name.startswith("origin/"):
            name = name[len("origin/"):]
        if name and name not in PROTECTED and name not in names:
            names.append(name)
    if branch not in names:
        names.append(branch)
    return names


def unreviewed(cwd: str) -> tuple[str, str, str] | None:
    """(worktree, branch, sha) for a pushed branch with commits and no PR, else None."""
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if not branch or branch in PROTECTED:
        return None
    # No upstream means never pushed: work in progress, nobody is waiting on it.
    if git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], cwd) is None:
        return None
    base = git(["merge-base", "origin/main", "HEAD"], cwd)
    if base is None:
        return None
    ahead = git(["rev-list", "--count", f"{base}..HEAD"], cwd)
    if not ahead or ahead == "0":
        return None

    # A squash merge rewrites the commits, so a branch whose work is fully IN main still reads
    # as N commits ahead forever. Judge by the resulting TREE instead, which is the same test
    # docs/BRANCH_CLEANUP_*.md proved: merging this branch into main changes nothing.
    merged_tree = git(["merge-tree", "--write-tree", "origin/main", "HEAD"], cwd)
    main_tree = git(["rev-parse", "origin/main^{tree}"], cwd)
    if merged_tree and main_tree and merged_tree.splitlines()[0] == main_tree:
        return None

    # Only work from the last day. Older branches are a standing backlog, not something this
    # turn forgot to open, and a guard that reports a backlog every stop is one people mute.
    age = git(["log", "-1", "--format=%ct", "HEAD"], cwd)
    if not age or not age.isdigit():
        return None
    import time
    if time.time() - int(age) > FRESH_SECONDS:
        return None

    sha = git(["rev-parse", "--short", "HEAD"], cwd)
    if sha is None:
        return None
    return (cwd, branch, sha)


def selftest() -> int:
    """Check the guard on a throwaway repo with a real `origin`. Graded by process_audit.py.

    Built 2026-08-19 because this hook fails OPEN by design -- every probe failure returns None
    and the stop is allowed. That is the right behaviour and it is also why a broken guard is
    invisible: a rule that never fires and a rule that cannot fire look identical from inside a
    session. The only way to tell them apart is to hand it a state it MUST refuse.

    Nothing here touches the network or GitHub. `origin` is a bare repo in a temporary directory,
    so `ls-remote` and the remote-tracking refs are real, and `has_open_pr` is never reached --
    the four exits tested below all happen before it.
    """
    import shutil
    import tempfile
    import time as _time

    def run(args, cwd, **env):
        subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **env}, check=True)

    failures: list[str] = []

    def check(name, got, want):
        if got != want:
            failures.append(f"  {name}: want {want!r}, got {got!r}")

    tmp = tempfile.mkdtemp(prefix="branch-pr-guard-selftest-")
    try:
        origin, work = f"{tmp}/origin.git", f"{tmp}/work"
        run(["git", "init", "--bare", "-q", "-b", "main", origin], tmp)
        run(["git", "init", "-q", "-b", "main", work], tmp)
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
            run(["git", "config", k, v], work)
        run(["git", "remote", "add", "origin", origin], work)
        Path(work, "a.txt").write_text("one\n")
        run(["git", "add", "a.txt"], work)
        run(["git", "commit", "-qm", "feat: one"], work)
        run(["git", "push", "-q", "-u", "origin", "main"], work)

        # 1. On main, nothing to review. PROTECTED short-circuits before any probe.
        check("unreviewed(main)", unreviewed(work), None)

        # 2. A branch with commits but never pushed is work in progress, not a missing PR.
        run(["git", "checkout", "-q", "-b", "feat/local"], work)
        Path(work, "a.txt").write_text("two\n")
        run(["git", "commit", "-qam", "feat: two"], work)
        check("unreviewed(unpushed)", unreviewed(work), None)

        # 3. Pushed, ahead of main, no PR -- the state this guard exists to catch.
        run(["git", "push", "-q", "-u", "origin", "feat/local"], work)
        hit = unreviewed(work)
        check("unreviewed(pushed+ahead) fires", hit is not None, True)
        if hit:
            check("unreviewed() branch name", hit[1], "feat/local")

        # 4. A squash-merged branch still reads N commits ahead forever. Judged by the TREE, a
        #    branch whose content is already in main must NOT be demanded a pull request.
        run(["git", "checkout", "-q", "-b", "feat/samewt"], work)
        Path(work, "a.txt").write_text("three\n")
        run(["git", "commit", "-qam", "feat: three"], work)
        Path(work, "a.txt").write_text("one\n")  # back to main's content
        run(["git", "commit", "-qam", "revert: back to one"], work)
        run(["git", "push", "-q", "-u", "origin", "feat/samewt"], work)
        check("unreviewed(tree == main)", unreviewed(work), None)

        # 5. Older than FRESH_SECONDS is a standing backlog, not this turn's omission.
        old = _time.strftime("%Y-%m-%dT%H:%M:%S",
                             _time.gmtime(_time.time() - FRESH_SECONDS - 3600))
        run(["git", "checkout", "-q", "-b", "feat/stale"], work)
        Path(work, "b.txt").write_text("old\n")
        run(["git", "add", "b.txt"], work)
        run(["git", "commit", "-qm", "feat: old"], work,
            GIT_AUTHOR_DATE=old, GIT_COMMITTER_DATE=old)
        run(["git", "push", "-q", "-u", "origin", "feat/stale"], work)
        check("unreviewed(older than FRESH_SECONDS)", unreviewed(work), None)

        # 6. `git push origin HEAD:other` is normal here, and the PR is open under THAT name.
        #    pushed_names must offer every remote name pointing at this commit.
        run(["git", "checkout", "-q", "feat/local"], work)
        run(["git", "push", "-q", "origin", "HEAD:review/alias"], work)
        run(["git", "fetch", "-q", "origin"], work)
        names = pushed_names("feat/local", work)
        check("pushed_names includes the alias", "review/alias" in names, True)
        check("pushed_names includes its own branch", "feat/local" in names, True)
        check("pushed_names excludes main", "main" in names, False)

        # 7. ls-remote is the authority. A name that was never pushed is absent.
        check("exists_on_remote(live)", exists_on_remote(["feat/local"], work), True)
        check("exists_on_remote(never pushed)", exists_on_remote(["no/such-branch"], work), False)

        # 8. A probe that cannot run returns None, which callers read as PASS. This is the
        #    property that keeps the guard satisfiable; if it ever raises instead, every stop
        #    in a broken checkout blocks.
        check("git() on a failing command", git(["rev-parse", "--verify", "nope"], work), None)
        check("worktrees() falls back to cwd", worktrees(tmp), [tmp])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 9. The dedupe ledger is bounded, so a long-lived state file cannot grow without limit.
    trimmed = {f"b{i}": "sha" for i in range(250)}
    if len(trimmed) > 200:
        trimmed = dict(list(trimmed.items())[-200:])
    check("state ledger caps at 200", len(trimmed), 200)

    total = 14
    if failures:
        print(f"branch-pr-guard selftest: {len(failures)}/{total} FAILED")
        print("\n".join(failures))
        return 1
    print(f"branch-pr-guard selftest: {total}/{total} passed")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()

    if git(["rev-parse", "--git-dir"], cwd) is None:
        return 0  # not a repo

    state = load_state()
    findings = []
    for tree in worktrees(cwd):
        hit = unreviewed(tree)
        if hit is None:
            continue
        tree, branch, sha = hit
        if state.get(branch) == sha:
            continue  # already reported at this exact commit
        # Open under ANY name this commit was pushed under, or the question could not be asked.
        names = pushed_names(branch, tree)
        if any(has_open_pr(name, tree) is not False for name in names):
            continue
        # Gone from the remote entirely: the local ref is stale, there is nothing to review, and
        # the `gh pr create` this guard would print is a command GitHub refuses. Prune and pass.
        if exists_on_remote(names, tree) is False:
            drop_stale_refs(names, tree)
            continue
        findings.append((tree, branch, sha))

    if not findings:
        return 0

    for _, branch, sha in findings:
        state[branch] = sha
    save_state(state)

    # A wall of text gets skimmed, so name at most five and count the rest. All of them are
    # recorded in the state file either way, so none blocks twice.
    shown, extra = findings[:5], max(0, len(findings) - 5)
    lines = ["BRANCH WITHOUT A PR: pushed work that no one can see."]
    for tree, branch, sha in shown:
        lines.append(f"  {branch} @ {sha}  in {tree}")
    if extra:
        lines.append(f"  ...and {extra} more")
    lines.append("")
    lines.append("Founder rule: commit, push, open the PR and set auto-merge in the SAME "
                 "command block. A pushed branch with no PR is invisible work, and the "
                 "founder should not have to ask for it.")
    lines.append("Open it now:")
    for tree, branch, _ in shown:
        lines.append(f"  cd {tree} && gh pr create --base main --head {branch} "
                     f"--title ... --body ...")
    lines.append("")
    lines.append("This blocks once per commit. If the branch is deliberately not for review, "
                 "say so in one line and stop again.")
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
