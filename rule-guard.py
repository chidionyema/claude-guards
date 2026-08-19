#!/usr/bin/env python3
"""PreToolUse guard: turn written rules into refusals.

WHY THIS EXISTS
---------------
On 2026-08-17 the founder asked whether the rules we enforce are working. Measured:

  13 hook scripts installed, and exactly ONE of them can block anything (hang-guard.py,
  about unbounded greps). Every other hook measures cost, accounts for context, or injects
  memory. There was no guard anywhere about commits, diffs, PRs or claims.

  333 memory files, two of which describe the exact diff-direction mistake made twice that
  same session, with the memory loaded in context both times.

So the conclusion is not "write the rule down more clearly". A rule that is READ does not
stop anything; a rule that RUNS does. This file is where a rule becomes a refusal.

HOW IT FAILS
------------
Open. Any exception, any unparseable payload, any git failure -> exit 0 and the command
proceeds. There are ~18 Claude processes against this estate, and a guard that wedges them
all is a worse outage than any rule it enforces.

EVERY RULE HAS AN ESCAPE
------------------------
Each rule names a marker you can add to the command to proceed anyway. That is deliberate:
the guard's job is to stop a mistake made by ACCIDENT, and to force the intent to be stated
out loud when it is not an accident. A rule with no escape gets disabled the first time it
is wrong, and then it protects nothing.

ADDING A RULE
-------------
Add a function to RULES. It takes the command string and returns a refusal message or None.
Then add a case to selftest(). `python3 rule-guard.py --selftest` must pass before wiring.
A rule with no selftest case is not a rule; it is a comment.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

REPO = "/Users/chidionyema/Documents/code/prospector"

#: The tree the command being judged will actually run in. A hardcoded REPO graded the shared
#: checkout's branch even when the work was in a worktree, so an 8-file PR could be refused for
#: a diff it had nothing to do with. The only way past was the override marker, which teaches
#: you to wave the guard through.
_ACTIVE_REPO = REPO

#: A command that starts by changing directory is telling you where it runs. Nothing else in the
#: payload does: `cwd` is the SESSION's directory, which for a worktree session is the wrong one.
_LEADING_CD = re.compile(r"""(?:^|[\n;&|]\s*)cd\s+(?P<path>'[^']+'|"[^"]+"|[^\s;&|]+)""")


def _worktree_root(path: str) -> str | None:
    """`path` resolved to the top of its git worktree, or None when it is not in one."""
    if not path or not os.path.isdir(path):
        return None
    rc, out = _git("rev-parse", "--show-toplevel", cwd=path)
    return out.strip() if rc == 0 and out.strip() else None


#: `SP=/long/path` then `cd "$SP/wt-prune"` is how a long scratchpad path gets used, and an
#: unexpanded `$SP` resolves to no directory at all -- so the cd was ignored and the SESSION's
#: repo was graded instead. On 2026-08-17 that refused a 1-file PR as "243 files", quoting the
#: shared checkout's branch, and the only way past was the override marker. Expanding the plain
#: assignments the command makes to itself is enough; no shell is invoked.
_ASSIGN = re.compile(r"""(?:^|[\n;&]\s*)(?P<name>[A-Za-z_]\w*)=(?P<val>'[^']*'|"[^"]*"|[^\s;&|]+)""")


def _expand(text: str, cmd: str) -> str:
    """`$VAR` and `${VAR}` in `text`, filled from assignments made earlier in `cmd`."""
    for m in _ASSIGN.finditer(cmd):
        val = m.group("val").strip("'\"")
        text = text.replace("${" + m.group("name") + "}", val).replace("$" + m.group("name"), val)
    return text


def _repo_for(cmd: str, session_cwd: str | None) -> str:
    """The worktree this command runs in. Falls back to REPO, so behaviour never gets worse."""
    for m in _LEADING_CD.finditer(cmd):
        root = _worktree_root(_expand(m.group("path").strip("'\""), cmd))
        if root:
            return root
    return _worktree_root(session_cwd or "") or REPO


def _git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    cwd = cwd or _ACTIVE_REPO
    try:
        p = subprocess.run(("git", *args), cwd=cwd, capture_output=True,
                           text=True, timeout=20)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _escape(marker: str) -> str:
    return (f"\n\nIf you mean it, append  # {marker}  to the command and say in your reply "
            f"why this case is different.")


# ---------------------------------------------------------------- rules

_ADD_ALL_RE = re.compile(r"\bgit\s+(?:-\S+\s+|--\S+(?:=\S+)?\s+)*add\s+(?:-A\b|--all\b|\.(?:\s|$))")


def rule_add_all(cmd: str) -> str | None:
    """`store/` and `storage/` are TRACKED runtime state that pytest writes to.

    `git add -A` here stages whatever the test suite happened to leave behind. The rule has
    been in CLAUDE.md for months and is restated in every handoff, which is how we know
    restating it does not work."""
    if "add-all-intended" in cmd:
        return None
    if _ADD_ALL_RE.search(cmd):
        return ("BLOCKED by rule-guard: `git add -A` / `git add .` in this estate.\n"
                "store/ and storage/ are tracked runtime state that pytest writes to, so this "
                "stages another process's test output.\n"
                "Stage explicit paths instead:  git add -- path/one path/two"
                + _escape("add-all-intended"))
    return None


_NO_VERIFY_RE = re.compile(r"\bgit\s+commit\b[^|;&]*(?:--no-verify\b|\s-n\b)")


def rule_no_verify(cmd: str) -> str | None:
    """Skipping the gate is a decision, not a convenience."""
    if "no-verify-intended" in cmd:
        return None
    if _NO_VERIFY_RE.search(cmd):
        return ("BLOCKED by rule-guard: `git commit --no-verify`.\n"
                "The permission classifier has refused this twice already. Use the isolated "
                "worktree, or state why the gate must be skipped."
                + _escape("no-verify-intended"))
    return None


_LOCK_RE = re.compile(r"\brm\b[^|;&]*index\.lock")


def rule_index_lock(cmd: str) -> str | None:
    """That lock is another session's live commit, not litter."""
    if "lock-removal-intended" in cmd:
        return None
    if _LOCK_RE.search(cmd):
        return ("BLOCKED by rule-guard: removing .git/index.lock.\n"
                "Sessions share one index here. That lock is another session's commit in "
                "progress; deleting it corrupts their commit. Queue and wait."
                + _escape("lock-removal-intended"))
    return None


_DIFF_RE = re.compile(r"\bgit\s+diff\b([^|;&]*)")
#: A word that could be a ref. Naming specific branches here made the rule expire with them, so
#: the shape is checked first and git is asked second (`_is_ref`), which names nothing.
_REFISH = re.compile(r"^[\w.][\w.\-/+]*$")


def _is_ref(word: str) -> bool:
    """True when git resolves `word` to a commit. Cheap, and it cannot go stale."""
    if not _REFISH.match(word) or os.path.exists(os.path.join(_ACTIVE_REPO, word)):
        return False  # a path that looks like a ref is a path
    rc, _ = _git("rev-parse", "--verify", "--quiet", word + "^{commit}")
    return rc == 0


def rule_two_dot_diff(cmd: str) -> str | None:
    """A two-point diff against a branch that has MOVED is not a merge outcome.

    `git diff origin/main branch` answers "how do these two trees differ", and every line
    main gained since the fork shows up as a deletion. Read as "merging this deletes 23,000
    lines", which is what happened on 2026-08-17 — twice, with two memories about it already
    written."""
    if "raw-diff-intended" in cmd or "merge-base" in cmd or "..." in cmd:
        return None
    for tail in _DIFF_RE.findall(cmd):
        words = [w for w in tail.split() if not w.startswith("-")]
        if "--" in tail.split():
            words = tail.split()[:tail.split().index("--")]
            words = [w for w in words if not w.startswith("-")]
        refs = [w for w in words if _is_ref(w)]
        if len(refs) >= 2 and ".." not in tail:
            return (f"BLOCKED by rule-guard: two-point `git diff {' '.join(refs[:2])}`.\n"
                    "Against a branch that has moved, this is NOT what a merge would do — every "
                    "line the other side gained since the fork prints as a deletion.\n"
                    "For what a merge applies:  git diff $(git merge-base A B) B\n"
                    "For whether it conflicts:  git merge-tree --write-tree A B"
                    + _escape("raw-diff-intended"))
    return None


#: A PR bigger than this is not the small fix its title claims. #247 was 198 files.
PR_FILE_CEILING = 40


def rule_pr_size(cmd: str) -> str | None:
    """A PR whose diff is 40x its title is how a fix branch smuggles a whole integration in.

    PRs #247 and #248 were announced as a 5-file glossary change and an 18-file fix. Their
    merge base was 37 commits stale, so each actually carried 198 files and the entire
    integration branch. Nobody looked, because nothing made them look."""
    if "gh pr create" not in cmd or "large-pr-intended" in cmd:
        return None
    m = re.search(r"--base[= ]+(\S+)", cmd)
    base = m.group(1).strip("\"'") if m else "main"
    rc, head = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or not head:
        return None
    rc, mb = _git("merge-base", f"origin/{base}", "HEAD")
    if rc != 0 or not mb:
        return None
    rc, out = _git("diff", "--name-only", mb, "HEAD")
    if rc != 0:
        return None
    files = [ln for ln in out.splitlines() if ln.strip()]
    if len(files) <= PR_FILE_CEILING:
        return None
    rc, stat = _git("diff", "--shortstat", mb, "HEAD")
    return (f"BLOCKED by rule-guard: this PR is {len(files)} files, ceiling is "
            f"{PR_FILE_CEILING}.\n"
            f"  base            origin/{base}\n"
            f"  merge base      {mb[:12]}\n"
            f"  what it applies {stat}\n"
            "A branch this size is usually a stale base carrying somebody else's history, not "
            "the change in your title. Rebase onto the current base, or say what the size is "
            "for in the PR body."
            + _escape("large-pr-intended"))


#: Directories the ENGINE writes while it runs. Staging them puts a day of ledger churn in the
#: diff, which is how a branch reaches hundreds of files with only a handful of them code.
#: Stopping it at the `git add` is cheaper than stripping it out afterwards.
_RUNTIME_PREFIXES = ("store/", "storage/", "signals/", "corpora/", "graphify-out/",
                     ".popdd/", ".backfill-logs/", ".lux/receipts/", "scratchpad/")

#: Quoted text is a commit MESSAGE, not a path. `git commit -m "rotate store/prospector.jsonl"`
#: names the file in prose and stages nothing; firing on it would be the rule crying wolf on the
#: exact commit that fixes the problem.
_QUOTED = re.compile(r"""'[^']*'|"[^"]*\"""")
_GIT_STAGING = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)*(?:add|commit)\b")


def rule_runtime_state(cmd: str) -> str | None:
    if "runtime-state-intended" in cmd or not _GIT_STAGING.search(cmd):
        return None
    scan = _QUOTED.sub(" ", cmd)
    hits = sorted({p for p in _RUNTIME_PREFIXES
                   if re.search(rf"(?:^|[\s=]){re.escape(p)}\S", scan)})
    if not hits:
        return None
    return ("BLOCKED by rule-guard: this stages runtime state, not code.\n"
            f"  paths            {', '.join(hits)}\n"
            "  why              the engine rewrites these every tick, so this puts a day of\n"
            "                   ledger churn in your diff\n"
            "Name the code paths explicitly: git commit --only -m 'msg' -- path/one.py path/two.py"
            + _escape("runtime-state-intended"))


_GIT_COMMIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)*commit\b")


def _shared_checkout_refusal(active_repo: str, branch: str) -> str | None:
    """REFUSE a commit made in the shared checkout on a named branch.

    The invariant: only a task worktree sits on a task branch, and every long-lived checkout sits
    on main. Several sessions share this tree and its index, so a commit here lands on whatever
    branch the last session left behind, and that branch grows without anyone choosing it.

    This was a NOTE until 2026-08-17 and a note was worth nothing. `integrate/minimax-into-main`
    took 105 commits and 743 lines of uncommitted work in this checkout, on one disk, with no
    remote for part of that time. Sessions saw the note, appended `shared-checkout-intended`, and
    committed anyway -- so the branch kept growing and the founder had to be the one who noticed,
    twice. A fence every caller can wave past is not a fence. It refuses now.

    The branch name is read to SHOW it, never to decide. A rule that knows one branch's name is
    dead the day that branch is.
    """
    if os.path.realpath(active_repo) != os.path.realpath(REPO):
        return None  # already in a worktree, which is the point
    if branch in ("HEAD", ""):
        return None  # detached: nothing accumulates
    return (f"BLOCKED by rule-guard: commit into the SHARED checkout, on `{branch}`.\n"
            f"  {REPO}\n"
            "  invariant        work happens in a task worktree; this checkout tracks main\n"
            "  why              several sessions share this tree and its index, so the branch\n"
            "                   grows without anyone choosing it, on one disk, with no PR\n"
            "  instead          git worktree add --detach ../wt-<name> origin/main\n"
            "                   ./scripts/setup_worktree.sh ../wt-<name>\n"
            "                   then commit THERE and open a PR"
            + _escape("shared-checkout-intended"))


def rule_commit_in_shared_checkout(cmd: str) -> str | None:
    if "shared-checkout-intended" in cmd or not _GIT_COMMIT.search(cmd):
        return None
    rc, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return None  # fail open, always
    return _shared_checkout_refusal(_ACTIVE_REPO, branch.strip())


#: Every way a merge is actually typed here. The REST endpoint was added on 2026-08-18: the fence
#: matched only `gh pr merge`, so `gh api -X PUT .../pulls/324/merge` walked straight past it.
#: PR #324 was merged that way at 07:01:13 with `python` still running; the merge then cancelled
#: that run at 07:01:58 and `ci-ok` concluded failure at 07:02:13 -- the same shape as #315, an
#: hour after #315 was cleaned up. A fence that names one spelling of the command is not a fence.
_GH_MERGE = re.compile(r"\bgh\s+pr\s+merge\b|/pulls/\d+/merge\b")
_GH_MERGE_NUM = re.compile(r"\bgh\s+pr\s+merge\s+(?:--?\S+(?:=\S+)?\s+)*?(\d+)\b"
                           r"|/pulls/(\d+)/merge\b")

#: States meaning the job has not finished. Merging on one of these is how three of main's four
#: runs on 2026-08-17 were cancelled: each merge landed while the previous run was still queued,
#: and GitHub keeps at most ONE run pending per concurrency group, so the next one evicted it.
_PENDING_STATES = {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED"}

#: States that count as green. SKIPPED and NEUTRAL belong here: a path filter deciding the web
#: lane is not needed for a Python-only diff is a real answer, not a missing one.
_OK_STATES = {"SUCCESS", "SKIPPED", "NEUTRAL"}


def _merge_refusal(pr: str, states: list[tuple[str, str]] | None) -> str | None:
    """Refuse `gh pr merge <pr>`? Pure, given the checks, so the decision is testable offline.

    `states` is (check name, state) pairs, or None when they could not be read at all.
    """
    if states is None:
        return (f"BLOCKED by rule-guard: could not read the CI checks for PR #{pr}.\n"
                "  why              a merge is the one irreversible step here, so an unknown\n"
                "                   verdict is treated as a red one, not waved through\n"
                "  instead          gh pr checks " + pr + _escape("merge-red-intended"))
    if not states:
        return (f"BLOCKED by rule-guard: PR #{pr} has NO checks at all.\n"
                "  why              main ran commit 5b8d010 in production on 2026-08-17 with\n"
                "                   zero finished runs; 'no checks' looked identical to green\n"
                "  instead          push a commit that triggers CI, or wait for the run to\n"
                "                   register, then re-read: gh pr checks " + pr
                + _escape("merge-red-intended"))

    waiting = [n for n, s in states if s.upper() in _PENDING_STATES]
    red = [f"{n}={s.lower()}" for n, s in states
           if s.upper() not in _OK_STATES and s.upper() not in _PENDING_STATES]
    if red:
        return (f"BLOCKED by rule-guard: PR #{pr} is not green — {', '.join(red[:6])}.\n"
                "  why              nothing on GitHub stops this: branch protection needs a\n"
                "                   paid plan or a public repo, so this hook is the only fence\n"
                "  instead          fix the failure, or merge the fix for it first\n"
                "  note             `gh pr checks --watch` exits 0 even when jobs failed, so\n"
                "                   read the states, never the exit code\n"
                "  no override      `merge-red-intended` does not open this one. A check that\n"
                "                   finished and did not pass is an answer, not an outage.")
    if waiting:
        return (f"BLOCKED by rule-guard: PR #{pr} still has {len(waiting)} check(s) running — "
                f"{', '.join(waiting[:6])}.\n"
                "  why              merging now cancels main's queued run: GitHub keeps one\n"
                "                   run pending per concurrency group and evicts the waiter\n"
                "  instead          wait for it, then re-read: gh pr checks " + pr
                + "\n  no override      `merge-red-intended` does not open this one.")
    return None


def _failed_jobs(run_id: str) -> list[str]:
    """Names of the jobs in `run_id` that concluded FAILURE. Empty when none, or unreadable.

    `ci-ok` is excluded because it is an aggregator, not a measurement. It reads its needs\'
    results and fails when any of them is not `success` or `skipped`, so a CANCELLED job makes
    it fail. Counting it here would re-create the exact false red this function exists to
    remove: run 32109476818 was cancelled with zero lane failures, and ci-ok alone still
    reported failure. A real breakage always shows up as a failed LANE job.

    Read through the REST API deliberately. `gh run view` and `gh pr` go through GraphQL, which
    this repo's token cannot use (`Resource not accessible by integration`, HTTP 403), while the
    same token reads REST fine. Measured 2026-08-18 inside one run: eleven REST calls succeeded
    and the single GraphQL call 403ed.
    """
    try:
        p = subprocess.run(
            ("gh", "api", f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs?per_page=100",
             "--jq", '.jobs[] | select(.conclusion == "failure") | select(.name != "ci-ok") | .name'),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _main_red_refusal() -> str | None:
    """Is main's own last finished CI run red? Returns the refusal text, or None.

    Fails OPEN, unlike the PR check above. The PR's own verdict already fails closed, so a second
    closed fence on an unreadable answer would wedge every merge on a GitHub hiccup. This one only
    ever adds a refusal it can prove.
    """
    try:
        p = subprocess.run(
            ("gh", "run", "list", "--branch", "main", "--workflow", "ci.yml",
             "--status", "completed", "--limit", "1",
             "--json", "conclusion,databaseId,headSha",
             "--jq", '.[] | "\\(.conclusion)\\t\\(.databaseId)\\t\\(.headSha)"'),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    row = p.stdout.strip().split("\t")
    if p.returncode != 0 or len(row) != 3 or row[0].upper() in ("SUCCESS", "SKIPPED", "NEUTRAL"):
        return None
    conclusion, run_id, sha = row

    # A run-level conclusion is not a verdict on the code. `cancelled` in particular measures
    # NOTHING: until 2026-08-18 ci.yml carried `cancel-in-progress: true` unconditionally, and
    # `github.ref` is `refs/heads/main` on every push to main, so every merge cancelled main's own
    # in-flight verification. 38 of main's last 94 CI runs are cancelled for that one reason. This
    # fence read the newest of them as "main is red" and refused every merge -- including the
    # merge that fixes it. A fence that cannot be satisfied is an outage, not a fence.
    #
    # Grade the JOBS instead. A job that concluded `failure` is a measurement and still blocks,
    # even inside a cancelled run. A cancelled run with no failed job is an absence of evidence.
    failed = _failed_jobs(run_id)
    if not failed:
        return None
    conclusion = f"{conclusion.lower()}, with {', '.join(failed)} failed"
    return (f"BLOCKED by rule-guard: main's own last CI run is {conclusion} "
            f"(run {run_id}, {sha[:7]}).\n"
            "  why              a merge onto a red main inherits the breakage and hides it\n"
            "                   behind its own red. On 2026-08-18 that turned one bad squash\n"
            "                   into 23 failures on every open pull request for five hours\n"
            "  instead          merge the fix for main FIRST, then come back to this one\n"
            "  override         append `# main-is-red` when THIS merge is that fix")


def _merge_verdict(pr: str, states: list[tuple[str, str]] | None,
                   escaped: bool, main_red: str | None, fixing_main: bool) -> str | None:
    """The whole merge decision, pure, so every branch of it is tested offline.

    Two fences, in order. The PR's own checks decide first, and `merge-red-intended` opens
    exactly one of those outcomes: `states is None`, which is GitHub not answering. A check that
    finished and did not pass is an answer.

    Then main's own last CI run. Merging onto a red main is how one bad commit became twenty-three
    failures on every open pull request: each merge inherits the breakage and hides it behind its
    own red, so nobody can tell whose fault it is. `main-is-red` is the marker for the merge that
    fixes it, and it says out loud what is being done.
    """
    refusal = _merge_refusal(pr, states)
    if refusal is not None:
        if escaped and states is None:
            return None    # the outage case, deliberately overridden
        return refusal
    if main_red and not fixing_main:
        return main_red
    return None


def _pr_check_states(pr: str) -> list[tuple[str, str]] | None:
    """(name, state) for every check on `pr`, or None if the query itself failed."""
    try:
        p = subprocess.run(
            ("gh", "pr", "checks", pr, "--json", "name,state",
             "--jq", '.[] | "\\(.name)\\t\\(.state)"'),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    # `gh pr checks` exits 8 when checks are still pending and 1 when some failed, so the exit
    # code alone cannot separate "query worked, PR is red" from "query broke". Trust stdout:
    # rows parsed means the query worked.
    rows = [ln.split("\t", 1) for ln in p.stdout.splitlines() if "\t" in ln]
    if rows:
        return [(a, b) for a, b in rows]
    # No rows and a clean exit means a PR with no checks registered — a real, dangerous answer.
    return [] if p.returncode == 0 else None


def rule_merge_red_pr(cmd: str) -> str | None:
    """The merge is the irreversible step, so it is the one worth fencing.

    On 2026-08-17 four merges landed on main in 25 minutes. Three cancelled each other's CI and
    the fourth concluded failure, and the follower shipped the result to production inside 60
    seconds. Every control that should have stopped that is unavailable on this plan: both
    `/branches/main/protection` and `/rulesets` return 403 "Upgrade to GitHub Pro or make this
    repository public". So the fence has to live where the command is typed.

    Fails CLOSED. An unreadable verdict blocks, because failing open is precisely what let an
    untested commit reach production; the escape marker is there for a real GitHub outage.
    """
    if not _GH_MERGE.search(cmd):
        return None
    # The marker is read AFTER the checks now, and it no longer covers a check that finished
    # and did not pass. On 2026-08-18 PR #315 was merged with `python` cancelled and `ci-ok`
    # failed, on the argument that those checks were structurally impossible rather than red.
    # Its branch carried a stale copy of scripts/live_checkout.py, so the squash deleted 115
    # lines that #286 had added an hour earlier. main was red for 23 tests for the next five
    # hours and every open pull request inherited them. The hatch exists for a GitHub outage,
    # which is the `states is None` case. A concluded FAILURE or CANCELLED is not an outage.
    escaped = "merge-red-intended" in cmd
    m = _GH_MERGE_NUM.search(cmd)
    if m:
        pr = m.group(1) or m.group(2)    # `gh pr merge N` or `/pulls/N/merge`
    else:
        rc, out = _git("rev-parse", "--abbrev-ref", "HEAD")
        if rc != 0:
            return None  # no branch to resolve a PR from; not our call to block
        try:
            p = subprocess.run(("gh", "pr", "view", "--json", "number", "--jq", ".number"),
                               cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        pr = p.stdout.strip()
        if not pr.isdigit():
            return None
    return _merge_verdict(pr, _pr_check_states(pr), escaped,
                          _main_red_refusal(), "main-is-red" in cmd)


#: Rules that REFUSE the command. Each one matches on what the command does — a flag, a path — so
#: it stays true whatever the repo's branches are called.
RULES = (rule_add_all, rule_runtime_state, rule_no_verify, rule_index_lock, rule_two_dot_diff,
         rule_pr_size, rule_commit_in_shared_checkout, rule_merge_red_pr)

#: Rules that let the command through and say something. Empty since 2026-08-17: the one warning
#: that lived here, the shared-checkout commit, was ignored for 105 commits and is a refusal now.
WARN_RULES: tuple = ()


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    cases = [
        # (command, rule that must fire or None)
        ("git add -A", "rule_add_all"),
        ("git add --all", "rule_add_all"),
        ("git add .", "rule_add_all"),
        ("git add -A  # add-all-intended", None),
        ("git add -- scripts/ops_status.py", None),
        ("git add -p", None),
        ("git commit --no-verify -m x", "rule_no_verify"),
        ("git commit -n -m x", "rule_no_verify"),
        ("git commit -m 'no-verify is bad'", None),
        ("rm -f .git/index.lock", "rule_index_lock"),
        ("rm /Users/x/.git/worktrees/w/index.lock", "rule_index_lock"),
        ("git diff --stat origin/main HEAD", "rule_two_dot_diff"),
        # Two BRANCH-shaped refs, not a branch-and-HEAD. This used to name
        # `origin/pr/shelf-copy-glossary`, which has since been deleted from origin — so
        # `_is_ref` stopped resolving it, only one ref was found, and the case failed for a
        # reason that had nothing to do with the rule. A selftest must not depend on a ref
        # somebody can delete. `origin/main` twice is still two refs and cannot go stale.
        ("git diff origin/main origin/main", "rule_two_dot_diff"),
        ("git diff --shortstat $(git merge-base origin/main HEAD) HEAD", None),
        ("git diff origin/main...HEAD", None),
        ("git diff --stat origin/main HEAD  # raw-diff-intended", None),
        ("git diff -- prospector/config.py", None),
        ("git diff HEAD~1", None),
        ("echo git add -A is banned", "rule_add_all"),  # substring match is acceptable here
        ("git add store/catalog.sqlite3", "rule_runtime_state"),
        ("git commit --only -m x -- prospector/run.py store/index.json", "rule_runtime_state"),
        ("git add .popdd/last_verify.json", "rule_runtime_state"),
        # A message that NAMES the file stages nothing. The rule must not fire on the commit
        # that fixes the problem it is about.
        ('git commit -m "rotate store/prospector.jsonl"', None),
        ("git add -- prospector/inflight.py", None),
        ("git add store/catalog.sqlite3  # runtime-state-intended", None),
        ("ls store/inflight", None),  # not a staging command at all
        # A heredoc BODY is text, not a command. Writing a doc that quotes the rule,
        # or a commit message that explains it, must not trip the rule it quotes.
        ("git commit -F - -- docs/A.md <<MSG\nnever git add -A in a worktree\nMSG\n", None),
        ("python3 - <<'PY'\nprint('the git add -A rule')\nPY\n", None),
        # ...unless a shell is reading it, because then the body executes.
        ("bash <<EOF\ngit add -A\nEOF\n", "rule_add_all"),
    ]
    bad = 0
    for cmd, want in cases:
        got = None
        cmd = strip_heredocs(cmd)
        for rule in RULES:
            if rule.__name__ in ("rule_pr_size", "rule_commit_in_shared_checkout",
                                 "rule_merge_red_pr"):
                # These read live state -- the branch this process is standing on, or GitHub --
                # so their answer here depends on where the selftest was launched, not on `cmd`.
                # Covered separately below, against explicit inputs.
                continue
            if rule(cmd):
                got = rule.__name__
                break
        if got != want:
            bad += 1
            print(f"  FAIL  {cmd!r}\n        wanted {want}, got {got}")

    # Which tree a rule measures is itself a rule, and it is the one that was wrong.
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ~/.claude, not a repo
    for cmd, session_cwd, want in [
        (f"cd {REPO} && gh pr create", "/nonexistent", REPO),
        (f"cd '{REPO}'\ngh pr create", "/nonexistent", REPO),
        ("gh pr create", REPO, REPO),          # no cd: the session's own tree
        ("cd /nonexistent/nope && gh pr create", None, REPO),   # unusable cd -> fall back
        ("gh pr create", here, REPO),          # cwd outside any worktree -> fall back
        # The 2026-08-17 false refusal: the cd path was a shell variable, so it resolved to no
        # directory and the SESSION's repo got graded instead.
        (f"P={REPO}\ncd \"$P\"\ngh pr create", "/nonexistent", REPO),
        (f"P={os.path.dirname(REPO)}\ncd \"$P/{os.path.basename(REPO)}\"\ngh pr create",
         "/nonexistent", REPO),
    ]:
        got_repo = _repo_for(cmd, session_cwd)
        if got_repo != want:
            bad += 1
            print(f"  FAIL  _repo_for({cmd!r}, {session_cwd!r})\n"
                  f"        wanted {want}, got {got_repo}")
        else:
            cases.append((cmd, want))

    # The shared-checkout note, tested on its decision rather than on the repo's mood.
    for repo, branch, want_note in [
        (REPO, "some/long-lived-branch", True),
        (REPO, "main", True),          # the shared tree is shared whatever the branch is called
        (REPO, "HEAD", False),         # detached: nothing accumulates
        ("/Users/chidionyema/Documents/code/wt-recover", "fix/anything", False),
    ]:
        note = _shared_checkout_refusal(repo, branch)
        noted = note is not None
        if noted != want_note:
            bad += 1
            print(f"  FAIL  _shared_checkout_refusal({repo!r}, {branch!r})\n"
                  f"        wanted noted={want_note}, got {noted}")
        else:
            cases.append((f"{repo}@{branch}", want_note))

    # The merge fence, tested on its decision rather than against a live GitHub.
    for states, want_blocked, label in [
        ([("python", "SUCCESS"), ("nextjs", "SKIPPED"), ("guard", "NEUTRAL")], False, "all green"),
        # Tonight's PR #290 exactly: five green, two red. `gh pr checks --watch` exited 0 on it.
        ([("engine", "SUCCESS"), ("python", "FAILURE"), ("ci-ok", "FAILURE")], True, "red"),
        ([("python", "SUCCESS"), ("dotnet", "IN_PROGRESS")], True, "still running"),
        ([("python", "SUCCESS"), ("dotnet", "QUEUED")], True, "queued"),
        # A cancelled run is not a pass. Three of main's four runs ended this way.
        ([("python", "CANCELLED")], True, "cancelled"),
        ([], True, "no checks at all"),        # what 5b8d010 looked like
        (None, True, "checks unreadable"),     # fails CLOSED
    ]:
        blocked = _merge_refusal("290", states) is not None
        if blocked != want_blocked:
            bad += 1
            print(f"  FAIL  _merge_refusal({label})\n"
                  f"        wanted blocked={want_blocked}, got {blocked}")
        else:
            cases.append((f"merge/{label}", want_blocked))

    # What the escape marker may and may not open. It was unconditional until 2026-08-18, when
    # PR #315 was merged with `python` cancelled and `ci-ok` failed on the argument that those
    # checks could not have run; the squash deleted 115 lines #286 had added an hour earlier and
    # main was red for 23 tests for five hours. The marker now opens ONE outcome: GitHub did not
    # answer. A concluded failure, a cancelled job, no checks at all, and a run still going are
    # all answers.
    GREEN = [("python", "SUCCESS")]
    RED = [("python", "FAILURE")]
    for label, states, escaped, main_red, fixing, want_blocked in [
            ("outage + marker", None, True, None, False, False),
            ("outage, no marker", None, False, None, False, True),
            ("red + marker", RED, True, None, False, True),
            ("cancelled + marker", [("python", "CANCELLED")], True, None, False, True),
            ("no checks + marker", [], True, None, False, True),
            ("pending + marker", [("python", "IN_PROGRESS")], True, None, False, True),
            ("green, main green", GREEN, False, None, False, False),
            ("green, main red", GREEN, False, "main is red", False, True),
            ("green, main red, fixing", GREEN, False, "main is red", True, False),
            ("red, main red", RED, False, "main is red", True, True),
    ]:
        blocked = _merge_verdict("1", states, escaped, main_red, fixing) is not None
        if blocked != want_blocked:
            bad += 1
            print(f"  FAIL  _merge_verdict({label})\n"
                  f"        wanted blocked={want_blocked}, got {blocked}")
        else:
            cases.append((f"verdict/{label}", want_blocked))

    # Every spelling of a merge must reach the fence, and the PR number must come out of each.
    # `gh api .../pulls/N/merge` did not match until 2026-08-18, which is how #324 was merged
    # with its `python` job still running.
    for cmd, want_pr in [
            ("gh pr merge 324 --squash", "324"),
            ("gh pr merge --squash --delete-branch 324", "324"),
            ("gh api -X PUT repos/chidionyema/prospector/pulls/324/merge", "324"),
            ("gh api --method PUT /repos/o/r/pulls/9/merge -f merge_method=squash", "9")]:
        m = _GH_MERGE_NUM.search(cmd)
        got = (m.group(1) or m.group(2)) if m else None
        if not _GH_MERGE.search(cmd) or got != want_pr:
            bad += 1
            print(f"  FAIL  {cmd!r}\n        wanted pr={want_pr}, matched={bool(_GH_MERGE.search(cmd))} got={got}")
        else:
            cases.append((f"merge-spelling/{want_pr}", cmd))

    # The rule must ignore commands that are not a merge.
    for cmd, want in [("gh pr list --state open", None),
                      ("gh pr create --base main", None)]:
        got = "rule_merge_red_pr" if rule_merge_red_pr(cmd) else None
        if got != want:
            bad += 1
            print(f"  FAIL  {cmd!r}\n        wanted {want}, got {got}")
        else:
            cases.append((cmd, want))

    # A warning must not be able to become a refusal by accident. The two tuples decide different
    # exit codes, so a rule appearing in both would block on a path meant only to inform.
    for name, ok, why in [
        ("warn_rules_are_not_also_refusals",
         not (set(RULES) & set(WARN_RULES)), "a rule is in RULES and WARN_RULES"),
        # Pin the 2026-08-17 promotion. This was a WARN_RULE for months; sessions read the note,
        # appended the marker and committed anyway, and `integrate/minimax-into-main` reached 105
        # commits in the shared checkout. Demoting it back is how that happens again.
        ("shared_checkout_commit_is_a_refusal",
         rule_commit_in_shared_checkout in RULES
         and rule_commit_in_shared_checkout not in WARN_RULES
         and (_shared_checkout_refusal(REPO, "some/branch") or "").startswith("BLOCKED"),
         "the shared-checkout commit rule is not a refusal"),
        ("a_warning_does_not_say_blocked",
         all(not (r(c) or "").startswith("BLOCKED")
             for r in WARN_RULES
             for c in (f"cd {REPO} && git commit -m x",)), "a WARN_RULES message says BLOCKED"),
    ]:
        if ok:
            cases.append((name, True))
        else:
            bad += 1
            print(f"  FAIL  {name}: {why}")
    print(f"selftest: {len(cases) - bad}/{len(cases)} passed")
    return 1 if bad else 0


# ---------------------------------------------------------------- entry

_HEREDOC_START = re.compile(r"""<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")
_SHELL_HEREDOC = re.compile(r"\b(?:ba|z|k|da)?sh\b[^\n|;]*<<")


def strip_heredocs(cmd: str) -> str:
    """Drop heredoc BODIES before the rules judge a command.

    Why this exists. On 2026-08-19 this guard refused a commit whose only match was the
    add-all rule quoted inside the commit message. The command staged two explicit paths.
    Every rule below matches on the raw command string, so any heredoc carrying prose about
    a forbidden command -- a doc being written, a commit message, a python patch script --
    trips a fence it never went near. A guard that refuses correct commands trains people to
    reach for the escape marker, and after that it is not a guard.

    The carve-out is deliberate. `bash <<EOF` and friends EXECUTE the body, so those lines
    are commands and must still be judged. When a shell is reading the heredoc, nothing is
    stripped and the old behaviour stands.
    """
    if _SHELL_HEREDOC.search(cmd):
        return cmd
    lines = cmd.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        m = _HEREDOC_START.search(line)
        if not m:
            continue
        term = m.group(2)
        # Skip the body. An unterminated heredoc runs to the end of the command, so
        # everything after it is body, not command.
        while i < len(lines) and lines[i].strip() != term:
            i += 1
        if i < len(lines):
            out.append(lines[i])
            i += 1
    return "".join(out)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = str(payload.get("tool_input", {}).get("command", ""))
    if not cmd:
        return 0
    global _ACTIVE_REPO
    _ACTIVE_REPO = _repo_for(cmd, payload.get("cwd"))
    cmd = strip_heredocs(cmd)
    for rule in RULES:
        try:
            reason = rule(cmd)
        except Exception:
            continue  # fail open, always
        if reason:
            sys.stderr.write(reason + "\n")
            return 2
    for rule in WARN_RULES:
        try:
            note = rule(cmd)
        except Exception:
            continue  # fail open, always
        if note:
            # Exit 0 with a systemMessage: the command runs, and the note is shown once.
            json.dump({"systemMessage": note}, sys.stdout)
            sys.stdout.write("\n")
            break
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)  # fail open
