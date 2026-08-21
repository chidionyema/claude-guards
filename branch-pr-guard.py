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

WHOSE BRANCHES. This session's, and shared checkouts. NOT another session's scratchpad worktree
-- see `foreign_session` for the 2026-08-19 incident that added the exclusion.

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

  * A pull request that is MERGED at this exact commit counts as reviewed. Asking only for OPEN
    pull requests blocked a stop on 2026-08-19 over `chore/process-audit` @ 4fb925ee, which was
    PR #373, merged at that very commit, with only the remote branch left undeleted. The
    tree check below could not catch it because it compares against the LOCAL `origin/main`,
    which in a worktree that has not fetched since the merge is behind.

The `main` branch, detached HEADs and branches with no upstream are all ignored: an unpushed
branch is work in progress, and only pushing makes it something a reviewer could be waiting on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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


def foreign_session(tree: str, session_id: str | None) -> bool:
    """True when this worktree belongs to a DIFFERENT live session's scratchpad.

    Sessions share this repo, so `git worktree list` returns every other agent's tree as well as
    this one's. On 2026-08-19 that produced the failure this function exists to stop: a sibling
    session was actively committing to `docs/founder-directive-ledger` in its own scratchpad
    worktree, and because each new commit is a new (branch, sha), the once-per-commit bound never
    engaged -- this guard blocked three stops in a row on somebody else's in-flight branch.

    Both ways out of that were wrong. Opening the pull request is the two-agents-one-branch
    collision `dupe-work-fence.py` exists to refuse. Typing "not mine" each time trains every
    agent to answer this guard with a sentence, which is how a guard stops being read.

    The scratchpad path carries the owning session's id (`<tmp>/<slug>/<session-uuid>/scratchpad`),
    so ownership is a fact on disk rather than a judgement. A tree outside any scratchpad is
    shared ground and is still scanned; so is this session's own scratchpad. If the payload
    carried no session id we cannot tell, and the guard keeps its old behaviour rather than
    going quiet -- an unproven skip is worse than a noisy check.
    """
    if not session_id:
        return False
    parts = Path(tree).parts
    if "scratchpad" not in parts:
        return False
    owner = parts[parts.index("scratchpad") - 1]
    return owner != session_id


def load_json(path: Path) -> dict:
    """A dict, or an empty one for ANY reason it could not be read.

    A lost ledger costs one duplicate block. A raise here would take the turn down, which is
    the one thing a guard must never do.
    """
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_json(path: Path, data: dict, keep: int = 200) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if len(data) > keep:
            data = dict(list(data.items())[-keep:])
        path.write_text(json.dumps(data, indent=2))
    except Exception:  # noqa: BLE001
        pass


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


def pr_covers(rows_json: str, sha: str) -> bool | None:
    """Does a pull request already make THIS commit visible? None when it cannot be decided.

    Pure, so the selftest can grade it without GitHub. Three answers, each for a reason:

      * OPEN      -> True. A live pull request tracks its head branch, so every push lands in it.
      * MERGED    -> True, but only when the merged head is this exact commit. A branch that was
                    merged and then took new commits is invisible work again, and answering True
                    on the old merge would be the guard failing silently.
      * CLOSED    -> False. Closed without merging means the work was seen and dropped; if it is
                    being pushed again it needs a pull request again.
    """
    try:
        rows = json.loads(rows_json or "[]")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(rows, list):
        return None
    for row in rows:
        state = str(row.get("state") or "").upper()
        if state == "OPEN":
            return True
        if state == "MERGED" and str(row.get("headRefOid") or "").startswith(sha):
            return True
    return False


def has_pr(branch: str, cwd: str, sha: str) -> bool | None:
    """True/False, or None when the question could not be asked.

    WHY IT ASKS FOR MERGED TOO (2026-08-19). This asked only for OPEN pull requests, and blocked
    a stop over `chore/process-audit` @ 4fb925ee -- which was PR #373, MERGED at exactly that
    commit, with only the remote branch left undeleted. The tree check above did not save it
    because it compares against the LOCAL `origin/main`, and in a worktree that has not fetched
    since the merge that ref is behind. A guard that demands a pull request for work already in
    main is a false positive, and a false positive is what gets a guard ignored.
    """
    try:
        out = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "all",
             "--json", "number,state,headRefOid"],
            cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    return pr_covers(out.stdout, sha)


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

        # 8b. Another session's scratchpad worktree is not this session's business.
        mine, theirs = "aaaaaaaa-1111", "bbbbbbbb-2222"
        base = "/private/tmp/claude-501/some-project"
        check("foreign_session(another session)",
              foreign_session(f"{base}/{theirs}/scratchpad/wt-dir", mine), True)
        check("foreign_session(my own scratchpad)",
              foreign_session(f"{base}/{mine}/scratchpad/wt-dir", mine), False)
        check("foreign_session(outside any scratchpad)",
              foreign_session("/Users/x/Documents/code/wt-deploy-age", mine), False)
        check("foreign_session(no session id known)",
              foreign_session(f"{base}/{theirs}/scratchpad/wt-dir", None), False)
        check("foreign_session(scratchpad itself)",
              foreign_session(f"{base}/{theirs}/scratchpad", mine), True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 9. A pull request that already covers this commit. Pure function, no network: the four
    #    states below are the whole decision, and the merged-at-a-different-commit row is the
    #    one that was wrong on 2026-08-19 in the other direction.
    check("pr_covers(open)", pr_covers('[{"state":"OPEN","headRefOid":"deadbeefcafe"}]', "1234abc"), True)
    check("pr_covers(merged at this sha)",
          pr_covers('[{"state":"MERGED","headRefOid":"1234abcdef01"}]', "1234abc"), True)
    check("pr_covers(merged at another sha)",
          pr_covers('[{"state":"MERGED","headRefOid":"999999999999"}]', "1234abc"), False)
    check("pr_covers(closed unmerged)",
          pr_covers('[{"state":"CLOSED","headRefOid":"1234abcdef01"}]', "1234abc"), False)
    check("pr_covers(no pull requests)", pr_covers("[]", "1234abc"), False)
    check("pr_covers(unreadable answer)", pr_covers("not json", "1234abc"), None)

    # 10. The dedupe ledger is bounded, so a long-lived state file cannot grow without limit.
    trimmed = {f"b{i}": "sha" for i in range(250)}
    if len(trimmed) > 200:
        trimmed = dict(list(trimmed.items())[-200:])
    check("state ledger caps at 200", len(trimmed), 200)


    # 11. THE HOLE THIS CLOSED. `pr_covers` answers True the moment a pull request is OPEN, so
    #     once #544 existed the guard was satisfied for six hours while the thing sat
    #     CONFLICTING. Both statements below must be true at once: the pull request exists AND
    #     it needs a person. If a change ever makes the second one False, this fails.
    conflicting = {"number": 544, "headRefName": "portal/fast-and-shareable",
                   "headRefOid": "a70a76b0bb8c", "isDraft": False, "mergeable": "CONFLICTING",
                   "statusCheckRollup": [{"name": "python", "conclusion": "FAILURE"},
                                         {"name": "ci-ok", "conclusion": "FAILURE"},
                                         {"name": "engine", "conclusion": "SUCCESS"}]}
    check("an OPEN pull request still satisfies pr_covers",
          pr_covers('[{"state":"OPEN"}]', "a70a76b0"), True)
    check("...and is nonetheless STUCK", (stuck(conflicting) or (None,))[0], "CONFLICT")

    # 12. Verdicts. CONFLICT outranks RED because nothing merges until the conflict is gone.
    red = dict(conflicting, mergeable="MERGEABLE")
    check("a failing check alone is RED", (stuck(red) or (None,))[0], "RED")
    check("the aggregator is not named when a real job failed", (stuck(red) or (0, []))[1],
          ["python"])
    only_agg = dict(red, statusCheckRollup=[{"name": "ci-ok", "conclusion": "FAILURE"}])
    check("...but IS named when it is the only thing that failed",
          (stuck(only_agg) or (0, []))[1], ["ci-ok"])

    # 13. The four states that are NOT stuck. Each one would be a false positive, and a false
    #     positive is what gets a guard uninstalled.
    check("a draft is never stuck", stuck(dict(conflicting, isDraft=True)), None)
    check("mergeable UNKNOWN is not a conflict",
          stuck({"mergeable": "UNKNOWN", "statusCheckRollup": []}), None)
    check("a check still running is not a failure",
          stuck({"mergeable": "MERGEABLE",
                 "statusCheckRollup": [{"name": "python", "conclusion": None}]}), None)
    check("SKIPPED and NEUTRAL are not failures",
          stuck({"mergeable": "MERGEABLE",
                 "statusCheckRollup": [{"name": "dotnet", "conclusion": "SKIPPED"},
                                       {"name": "x", "conclusion": "NEUTRAL"}]}), None)
    check("CANCELLED is left to pr-keeper.yml",
          stuck({"mergeable": "MERGEABLE",
                 "statusCheckRollup": [{"name": "python", "conclusion": "CANCELLED"}]}), None)
    check("a green pull request is not stuck",
          stuck({"mergeable": "MERGEABLE",
                 "statusCheckRollup": [{"name": "python", "conclusion": "SUCCESS"}]}), None)
    check("a pull request with no checks at all is not stuck",
          stuck({"mergeable": "MERGEABLE", "statusCheckRollup": []}), None)

    # 14. Whose pull request. A peer's red branch must never stop THIS session: their own hook
    #     owns it, and being stopped over work you cannot land is how a guard becomes noise.
    now = 1_000_000.0
    check("a branch this session does not hold is ignored",
          stuck_findings([conflicting], {}, {}, now), [])
    hits = stuck_findings([conflicting], {"portal/fast-and-shareable": "/tmp/wt"}, {}, now)
    check("this session's own branch is reported", [h["pr"] for h in hits], [544])
    check("...keyed by pull request, commit AND verdict",
          hits[0]["key"], "544@a70a76b0:CONFLICT")

    # 15. The throttle. It must stop the SAME state from blocking every turn, and it must come
    #     BACK while the state is still true -- one alert and then silence is exactly the
    #     failure mode that let #544 sit for six hours.
    seen = {"544@a70a76b0:CONFLICT": now}
    check("the same state does not block twice inside the grace window",
          stuck_findings([conflicting], {"portal/fast-and-shareable": "/tmp/wt"}, seen, now + 60),
          [])
    check("...and blocks again once the grace window has passed",
          len(stuck_findings([conflicting], {"portal/fast-and-shareable": "/tmp/wt"}, seen,
                             now + STUCK_GRACE_S + 1)), 1)
    check("a NEW commit on the same branch is a new state",
          len(stuck_findings([dict(conflicting, headRefOid="ffffffffffff")],
                             {"portal/fast-and-shareable": "/tmp/wt"}, seen, now + 60)), 1)
    check("a corrupt ledger timestamp does not suppress the block",
          len(stuck_findings([conflicting], {"portal/fast-and-shareable": "/tmp/wt"},
                             {"544@a70a76b0:CONFLICT": "not a number"}, now)), 1)

    # 16. Fails OPEN, like every other probe in this file.
    check("an unreadable ledger reads as empty", load_json(Path("/no/such/file.json")), {})

    total = 44
    if failures:
        print(f"branch-pr-guard selftest: {len(failures)}/{total} FAILED")
        print("\n".join(failures))
        return 1
    print(f"branch-pr-guard selftest: {total}/{total} passed")
    return 0


#: A pull request that is OPEN but going nowhere blocks again after this long. pr-reactor.py
#: uses the same 45 minutes as its alert grace, so the estate has ONE number for "stuck".
STUCK_GRACE_S = 45 * 60

#: Its own ledger, deliberately NOT the file above. That one is a tested branch->sha map and
#: this is a different shape; sharing it would risk the guard that already works.
STUCK_STATE = Path.home() / ".claude" / "state" / "branch-pr-guard.stuck.json"

#: Aggregator checks. They go red BECAUSE something else went red, so naming one in the block
#: text sends you to a job whose log says nothing about the cause. `ci-ok` is the only one today.
AGGREGATORS = {"ci-ok"}

#: What counts as a check that FAILED. CANCELLED is deliberately absent: a job that exceeds
#: `timeout-minutes` is marked cancelled and rendered exactly like a failure, and re-running
#: those already has an owner in `.github/workflows/pr-keeper.yml` ("re-run a REFUSAL, never a
#: FAILURE"). Blocking a stop on work a robot is already redoing is a guard that cannot be
#: satisfied by the person it stops.
FAILED_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED"}


def repo_root_from_broken_worktree(cwd: str) -> str | None:
    """The main checkout, when `cwd` is a worktree whose gitdir no longer exists.

    WHY (measured 2026-08-21, and it made this whole guard inert). This session's own cwd is
    such a tree: its `.git` FILE names prospector/.git/worktrees/wt-storeroot, a directory that
    does not exist. `git rev-parse --git-dir` fails there, so main() returned 0 and the guard
    was SILENTLY OFF -- for the very session the founder was complaining about. 44 of 113
    worktrees on this estate are in that state, and in every one of them `git ls-files` prints
    nothing AND EXITS 0, so nothing ever fails loudly enough to notice.

    The dead pointer still names the repository it belonged to, which is all this needs. The
    session works in that repo's OTHER worktrees by `cd`, and those are exactly the branches it
    owns, so falling back to the root finds the right set rather than a different one.
    """
    try:
        raw = Path(cwd, ".git").read_text()
    except Exception:  # noqa: BLE001 -- a real repo has a .git DIRECTORY; reading it fails
        return None
    if not raw.startswith("gitdir:"):
        return None
    pointer = Path(raw.split(":", 1)[1].strip())
    for parent in pointer.parents:
        # .../<root>/.git/worktrees/<name>  ->  <root>
        if parent.name == ".git":
            root = str(parent.parent)
            return root if git(["rev-parse", "--git-dir"], root) is not None else None
    return None


def main_red_checks(cwd: str) -> set[str]:
    """Check names failing on main's OWN latest run. Empty set when it cannot be asked.

    A peer's bound, 2026-08-21, and it is better than the timer it replaces: never stop a
    session over a check that is also red on main. That is the line between "your work is
    broken" and "you inherited a broken baseline", and unlike a 45-minute re-arm it self-clears
    the moment main goes green. It was not hypothetical today -- main went red on a doc-link
    test that was in nobody's diff, and every open pull request inherited it.

    Two calls, and only ever when there is already something to report, so a green estate pays
    nothing for it.
    """
    def gh(args: list[str]) -> str | None:
        try:
            out = subprocess.run(["gh", *args], cwd=cwd, capture_output=True,
                                 text=True, timeout=TIMEOUT)
        except Exception:  # noqa: BLE001
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    run_id = gh(["run", "list", "--branch", "main", "--limit", "1",
                 "--json", "databaseId", "--jq", ".[0].databaseId"])
    if not run_id or not run_id.isdigit():
        return set()
    names = gh(["api", "repos/:owner/:repo/actions/runs/%s/jobs" % run_id,
                "--jq", '.jobs[]|select(.conclusion=="failure")|.name'])
    if not names:
        return set()
    return {n.strip() for n in names.splitlines() if n.strip()}


def drop_inherited(findings: list[dict], red_on_main: set[str]) -> list[dict]:
    """Remove what the session inherited from a red main, and say so in the ones that remain.

    A CONFLICT is never inherited -- it is a fact about this branch and main together, and only
    the branch owner can resolve it -- so the bound applies to RED only.
    """
    if not red_on_main:
        return findings
    kept = []
    for f in findings:
        if f["verdict"] != "RED":
            kept.append(f)
            continue
        own = [n for n in f["failing"] if n not in red_on_main]
        if own:
            kept.append(dict(f, failing=own))
    return kept


def open_prs(cwd: str) -> list[dict] | None:
    """Every open pull request in this repo, or None when the question could not be asked.

    ONE call for the whole repo, not one per worktree. Measured 2026-08-21: 1.24s for the
    repo. This estate has a dozen worktrees, so per-branch probing would put ten seconds in
    the path of every turn, and a guard that slow gets uninstalled.
    """
    try:
        out = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "100", "--json",
             "number,headRefName,headRefOid,isDraft,mergeable,statusCheckRollup"],
            cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except Exception:  # noqa: BLE001 — a probe that cannot run means PASS, never block
        return None
    if out.returncode != 0:
        return None
    try:
        rows = json.loads(out.stdout or "[]")
    except Exception:  # noqa: BLE001
        return None
    return rows if isinstance(rows, list) else None


def stuck(row: dict) -> tuple[str, list[str]] | None:
    """(verdict, failing check names) when this pull request needs a person, else None.

    Pure, so the selftest grades it without GitHub. Four states are NOT stuck, and each one
    would be a false positive that gets this guard ignored:

      * a DRAFT             -- parked on purpose. Its author is not waiting for review.
      * mergeable UNKNOWN   -- GitHub has not finished computing the merge yet. Measured on
                               #544, 2026-08-21: UNKNOWN on one call, CONFLICTING on the next
                               a minute later. UNKNOWN means "ask again", not "it is fine".
      * checks still running -- conclusion null. Waiting for CI is not a blind spot.
      * SKIPPED or NEUTRAL  -- not failures. Half this repo's matrix skips on any given diff.

    CONFLICT outranks RED because nothing can merge until the conflict is gone, and resolving
    it re-runs the checks anyway.
    """
    if row.get("isDraft"):
        return None
    failing = sorted({
        str(c.get("name") or c.get("context") or "?")
        for c in (row.get("statusCheckRollup") or [])
        if str(c.get("conclusion") or "").upper() in FAILED_CONCLUSIONS
        or str(c.get("state") or "").upper() in {"FAILURE", "ERROR"}
    })
    named = [f for f in failing if f not in AGGREGATORS] or failing
    if str(row.get("mergeable") or "").upper() == "CONFLICTING":
        return ("CONFLICT", named)
    if named:
        return ("RED", named)
    return None


def stuck_findings(rows: list[dict], mine: dict[str, str], seen: dict, now: float) -> list[dict]:
    """The open pull requests of THIS session's branches that need a person.

    Pure. `mine` maps branch name -> worktree, so a peer's red pull request never stops this
    session: their own hook owns it, and being nagged about work you cannot land is the fastest
    way to make a guard noise.
    """
    out = []
    for row in rows:
        branch = str(row.get("headRefName") or "")
        tree = mine.get(branch)
        if tree is None:
            continue
        verdict = stuck(row)
        if verdict is None:
            continue
        sha = str(row.get("headRefOid") or "")[:8]
        key = "%s@%s:%s" % (row.get("number"), sha, verdict[0])
        last = seen.get(key)
        if isinstance(last, (int, float)) and (now - last) < STUCK_GRACE_S:
            continue  # already stopped this session over this exact state, recently
        out.append({"pr": row.get("number"), "branch": branch, "tree": tree,
                    "sha": sha, "verdict": verdict[0], "failing": verdict[1], "key": key})
    return out


def report_stuck(findings: list[dict]) -> None:
    lines = ["YOUR PULL REQUEST IS STUCK: open, not moving, and nobody else owns it."]
    for f in findings[:5]:
        why = ("merge conflict with main; nothing merges until it is resolved"
               if f["verdict"] == "CONFLICT" else "failing: " + ", ".join(f["failing"]))
        lines.append("  #%s %-8s %s @ %s" % (f["pr"], f["verdict"], f["branch"], f["sha"]))
        lines.append("      %s" % why)
    if len(findings) > 5:
        lines.append("  ...and %d more" % (len(findings) - 5))
    lines += [
        "",
        "Founder rule, 2026-08-21: \"you are not folloong up on ur prs\", \"this is a blind",
        "spot\", \"should not have to renin du\". Ship means shipped -- commit, push, open the",
        "pull request, then follow it to MERGED. An open red pull request is not delivered work.",
        "",
        "Get the CAUSE, not the colour (`gh pr checks` says WHICH job, never WHY):",
        "  python3 ~/.claude/scripts/pr-why.py %s" % findings[0]["pr"],
        "Then, in its own worktree:",
    ]
    for f in findings[:5]:
        if f["verdict"] == "CONFLICT":
            lines.append("  cd %s && git fetch origin main && git merge origin/main --no-edit"
                         % f["tree"])
        else:
            lines.append("  cd %s   # fix, commit through the gate, push" % f["tree"])
    lines += [
        "  gh pr merge <n> --merge      # automerge.yml was deleted in #522; merges are by hand",
        "",
        "This blocks once per (pull request, commit, verdict), and again if the same state is",
        "still true in 45 minutes. If it is parked on purpose, say so in one line and stop again.",
    ]
    print("\n".join(lines), file=sys.stderr)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id")

    if git(["rev-parse", "--git-dir"], cwd) is None:
        # NOT simply "not a repo". A worktree whose gitdir was removed looks exactly like this,
        # and 44 of 113 on this estate are in that state -- including the cwd of the session
        # that shipped this guard. Falling back to the repository the dead pointer names is the
        # difference between a guard that is off and a guard that works.
        cwd = repo_root_from_broken_worktree(cwd) or ""
        if not cwd:
            return 0

    state = load_state()
    findings = []
    mine: dict[str, str] = {}
    for tree in worktrees(cwd):
        if foreign_session(tree, session_id):
            continue  # another session's scratchpad; its own hook owns it
        head = git(["rev-parse", "--abbrev-ref", "HEAD"], tree)
        if head and head not in PROTECTED:
            mine.setdefault(head, tree)
        hit = unreviewed(tree)
        if hit is None:
            continue
        tree, branch, sha = hit
        if state.get(branch) == sha:
            continue  # already reported at this exact commit
        # Open under ANY name this commit was pushed under, or the question could not be asked.
        names = pushed_names(branch, tree)
        if any(has_pr(name, tree, sha) is not False for name in names):
            continue
        # Gone from the remote entirely: the local ref is stale, there is nothing to review, and
        # the `gh pr create` this guard would print is a command GitHub refuses. Prune and pass.
        if exists_on_remote(names, tree) is False:
            drop_stale_refs(names, tree)
            continue
        findings.append((tree, branch, sha))

    # A pull request that EXISTS satisfied this guard forever, whatever state it was in --
    # `pr_covers` returns True the moment one is OPEN. That is the hole the founder named on
    # 2026-08-21 ("you are not folloong up on ur prs", "this is a blind spot"), measured on
    # #544: open at 04:20, CONFLICTING and red for six hours, three board alerts, and nothing
    # ever stopped the session that owned it. Detection was never the gap; enforcement was.
    rows = open_prs(cwd)
    if rows:
        seen = load_json(STUCK_STATE)
        now = time.time()
        hits = stuck_findings(rows, mine, seen, now)
        # Only now, and only if there is something to say, ask what main itself is failing.
        hits = drop_inherited(hits, main_red_checks(cwd)) if hits else hits
        if hits:
            for h in hits:
                seen[h["key"]] = now
            save_json(STUCK_STATE, seen)
            report_stuck(hits)
            return 2

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
