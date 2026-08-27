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
In Rego, in policy/command.rego, not here. Add an entry to `rules` with its `re`,
`marker`, `msg`, and the `must_match` / `must_not_match` examples that keep it
honest, then `opa test policy/command.rego policy/command_test.rego`.

The six rules still written in Python below are the ones Rego cannot express: each
one shells out to git or gh to ask a question about the live tree. They are the
backlog, not the pattern.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

#: One Mac's absolute path. Off that Mac the directory is simply not there, `_git`
#: answers "cannot tell" to every question, and every rule that asks git something
#: abstains IN SILENCE -- a guard that cannot see its subject permits and prints what
#: a clean run prints. CI found it: two rule_two_dot_diff cases got None. So fall back
#: to the tree this process is standing in, which on a runner is the checkout.
_HOME_REPO = "/Users/chidionyema/Documents/code/prospector"
REPO = _HOME_REPO if os.path.isdir(_HOME_REPO) else os.getcwd()

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
    """`$VAR`, `${VAR}` and `~` in `text`: assignments made earlier in `cmd`, then the environment. See test_incident_rule_guard_tilde_cd_graded_the_wrong_repo.py."""
    for m in _ASSIGN.finditer(cmd):
        val = m.group("val").strip("'\"")
        text = text.replace("${" + m.group("name") + "}", val).replace("$" + m.group("name"), val)
    return os.path.expanduser(os.path.expandvars(text))


# The Claude config directory became a git repository on 2026-08-21 (the governance repo).
# Before that it was not one, and `_worktree_root` returning nothing for it was what made a
# command run from there fall back to REPO. The moment it became a repo, every git lookup this
# guard makes -- the shared-checkout note, the branch checks at :429/:451/:511/:556 -- started
# grading ~/.claude instead of the product tree, silently and only for commands run from there.
# It is configuration for the agent, not a tree anyone opens a pull request against, so it is
# excluded by identity. Only the directory ITSELF: ~/.claude/worktrees holds real product
# worktrees and those must still resolve to themselves.
_CONFIG_DIR = os.path.realpath(os.path.expanduser("~/.claude"))


def _is_product_repo(root: str) -> bool:
    return bool(root) and os.path.realpath(root) != _CONFIG_DIR


#: A command that never cd's but runs everything through `git -C <path>` is telling you where
#: it runs just as loudly. On 2026-08-24 a command built a crew worktree entirely with -C and
#: then ran `gh pr create`; the guard graded the SESSION's repo instead and refused a 1-file
#: PR as "65 files" — the same wrong-repo class as the two incidents above, third variant.
_GIT_DASH_C = re.compile(r"""\bgit\s+-C\s+(?P<path>'[^']+'|"[^"]+"|[^\s;&|]+)""")

#: `--repo owner/name` names the repository outright and outranks every path guess. Fifth
#: variant of the wrong-repo class; see test_incident_rule_guard_repo_flag_graded_the_wrong_repo.py.
_GH_REPO_FLAG = re.compile(r"(?:--repo|-R)[=\s]+(?P<slug>[\w.-]+/[\w.-]+)")


def _repo_for(cmd: str, session_cwd: str | None) -> str:
    """The worktree this command runs in. Falls back to REPO, so behaviour never gets worse."""
    for pat in (_LEADING_CD, _GIT_DASH_C):
        for m in pat.finditer(cmd):
            root = _worktree_root(_expand(m.group("path").strip("'\""), cmd))
            if _is_product_repo(root):
                return root
    root = _worktree_root(session_cwd or "")
    return root if _is_product_repo(root) else REPO


def _sh(argv: list[str], timeout: int = 20) -> tuple[int, str]:
    """Run any CLI and return (rc, combined output). Never raises; rc != 0 means "cannot tell"."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


# ---- shim-proof subprocess: a PATH shim must never be able to call this guard back --------
# 2026-08-21, measured on this machine: a session installed a wrapper directory first on PATH
# whose `git` re-invoked THIS guard. `_git` below then ran the bare name "git", which resolved
# to that wrapper again, which ran the guard again, unbounded. Load 562, 1063 processes, 238
# live children all under 21s old, 24 MB of free RAM. This guard runs on EVERY Bash call in
# EVERY session, so one session's shim takes the whole machine down, and no session can see
# the loop from inside its own window.
#
# The fix has to be here rather than in the shim, because the shim is not the only one that
# will ever exist. Resolve the tool ONCE against a fixed system PATH and hand the child that
# same PATH, so no wrapper directory can be on it whatever the parent's PATH looks like.
# `shutil.which` returning None falls back to the bare name, which keeps this guard failing
# OPEN — a guard that cannot find git must not start refusing commits.
_SYSTEM_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def _real_tool(name: str) -> str:
    """Absolute path to the real `name`, looked up on the system PATH only."""
    return shutil.which(name, path=_SYSTEM_PATH) or name


def _clean_env() -> dict:
    """The current environment with PATH replaced by the system one. Nothing else changes."""
    env = dict(os.environ)
    env["PATH"] = _SYSTEM_PATH
    return env


def _git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    cwd = cwd or _ACTIVE_REPO
    try:
        p = subprocess.run((_real_tool("git"), *args), cwd=cwd, capture_output=True,
                           text=True, timeout=20, env=_clean_env())
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _escape(marker: str) -> str:
    return (f"\n\nIf you mean it, append  # {marker}  to the command and say in your reply "
            f"why this case is different.")


# ---------------------------------------------------------------- rules

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
    m = re.search(r"--head[= ]+(\S+)", cmd)
    if m and m.group(1).strip("\"'") != head:
        # The PR's declared head branch is not the branch this checkout is on, so the
        # diff below would be some other repo's history — the exact mistake that
        # refused a 1-file PR as "65 files" on 2026-08-24. A guard that cannot see
        # the change it is grading abstains rather than accuses.
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
                "                   register, then re-read: gh pr checks " + pr + "\n  first check      GitHub creates no pull_request run for a PR that conflicts with its base (crew#490, 2026-08-27:\n"
                "                   0 checks for 40 min; close/reopen and an empty commit changed nothing; merging main in produced 6).\n                   Read it before waiting: gh pr view " + pr + " --json mergeable --jq .mergeable ; CONFLICTING means merge the base in and push."
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
            (_real_tool("gh"), "api",
             f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs?per_page=100",
             "--jq", '.jobs[] | select(.conclusion == "failure") | select(.name != "ci-ok") | .name'),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30,
            env=_clean_env())
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
            (_real_tool("gh"), "run", "list", "--branch", "main", "--workflow", "ci.yml",
             "--status", "completed", "--limit", "1",
             "--json", "conclusion,databaseId,headSha",
             "--jq", '.[] | "\\(.conclusion)\\t\\(.databaseId)\\t\\(.headSha)"'),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30,
            env=_clean_env())
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


def _pr_check_states(pr: str, cmd: str = "") -> list[tuple[str, str]] | None:
    """(name, state) for every check on `pr`, or None if the query itself failed."""
    named = next((_GH_REPO_FLAG.search(s) for s in re.split(r"\|\||&&|[;|\n]", cmd) if _GH_MERGE.search(s)), None)  # the merge's own segment only
    try:
        p = subprocess.run(
            [_real_tool("gh"), "pr", "checks", pr, "--json", "name,state",
             "--jq", '.[] | "\\(.name)\\t\\(.state)"']
            + (["--repo", named.group("slug")] if named else []),
            cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30,
            env=_clean_env())
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
        # 2026-08-24: `gh pr merge "$PR"` — the number in a shell variable — reached this
        # fallback, `gh pr view` returned nothing useful, and the three `return None`s below
        # waved the merge through. PR #99 landed with its qa check unfinished; the check then
        # concluded FAILURE on merged code. The docstring above says fails CLOSED, and these
        # were the three paths that failed open. An unresolvable PR is now a refusal, not a
        # pass: the fix costs the author four characters — the PR number, written literally.
        _unresolved = ("BLOCKED by rule-guard: `gh pr merge` with no literal PR number, and "
                       "the PR could not be resolved from the checkout.\n"
                       "  why              a merge this guard cannot attribute is a merge it\n"
                       "                   cannot grade; PR #99 slipped through here with its\n"
                       "                   qa check still running (2026-08-24)\n"
                       "  instead          name the number in the command: gh pr merge <n>")
        rc, out = _git("rev-parse", "--abbrev-ref", "HEAD")
        if rc != 0:
            return _unresolved
        try:
            p = subprocess.run((_real_tool("gh"), "pr", "view", "--json", "number", "--jq", ".number"),
                               cwd=_ACTIVE_REPO, capture_output=True, text=True, timeout=30,
            env=_clean_env())
        except (OSError, subprocess.SubprocessError):
            return _unresolved
        pr = p.stdout.strip()
        if not pr.isdigit():
            return _unresolved
    return _merge_verdict(pr, _pr_check_states(pr, cmd), escaped,
                          _main_red_refusal(), "main-is-red" in cmd)


#: Rules that REFUSE the command. Each one matches on what the command does — a flag, a path — so
#: it stays true whatever the repo's branches are called.
# --- a machine repair restarts the machine, and a build was on it ---------------------------
#
# WHY. On 2026-08-19 at 20:26–20:32Z I repaired 10 standby machines with
# `fly machine update <id> -a prospector-ci --standby-for "" --yes`. That command RESTARTS the
# machine. A peer session's test suite was running on one of them. Their job died, and they
# spent the next stretch hunting "a rolling restart of 10 of 12 runners, 15s apart, with no new
# release" -- which was me, invisible to them, because sessions cannot see each other.
#
# THE CLASS is the one LAW 0's own worked example names: an agent action that silently destroys
# another agent's in-flight work. `push-pr-fence.py` already guards the CI-cancel version of it.
# This is the machine version. The fix is not "remember to check"; it is that the check runs
# whether or not anyone remembers.
#
# `start` is deliberately NOT matched: starting a stopped machine cannot interrupt a build.
# The check FAILS OPEN -- if gh is missing or GitHub is unreachable it allows the command --
# because a fleet repair is most needed exactly when GitHub is unhappy, and a guard that walls
# the box whenever it cannot see is a worse failure than the one it prevents.
_FLY_DISRUPT_RE = re.compile(
    r"\bfly\s+m(?:achine)?s?\s+(update|restart|stop|destroy)\b[^|;&\n]*?-a\s+(\S+)")

# Which repository's runners live on which Fly app. An app that is not a runner fleet is not
# this rule's business, so an unknown app is allowed through.
_RUNNER_APP_REPOS = {
    "prospector-ci": "chidionyema/prospector",
    "hermes-ci": "chidionyema/hermes",
}


def _busy_runners(repo: str) -> list[str]:
    """Names of `repo`'s runners that are mid-job. Empty when busy is zero OR unknowable.

    Separate from the rule so the selftest can stub it: the rule must be provable without
    depending on whatever CI happens to be doing when the selftest runs.
    """
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    rc, out = _sh([gh, "api", f"repos/{repo}/actions/runners",
                   "--jq", ".runners[] | select(.busy) | .name"])
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def rule_restart_kills_a_live_build(cmd: str) -> str | None:
    """Refuse a machine restart while that fleet has a runner mid-job."""
    if "runner-busy-intended" in cmd:
        return None
    m = _FLY_DISRUPT_RE.search(cmd)
    if not m:
        return None
    verb, app = m.group(1), m.group(2).strip("'\"")
    repo = _RUNNER_APP_REPOS.get(app)
    if repo is None:
        return None

    busy = _busy_runners(repo)
    if not busy:
        return None  # empty OR unknowable; failing open is the deliberate choice above

    return (f"BLOCKED by rule-guard: `fly machine {verb}` on {app} while "
            f"{len(busy)} runner(s) are MID-JOB.\n"
            f"Busy now: {', '.join(busy)}\n"
            f"`fly machine {verb}` restarts or removes the machine. If the job you kill belongs "
            f"to another session, they see a build that died as \"The self-hosted runner lost "
            f"communication with the server\" -- which reads as a failing test, from a cause "
            f"they cannot see. That is exactly what happened on 2026-08-19 at 20:26Z.\n"
            f"Wait for the fleet to go idle:\n"
            f"  gh api repos/{repo}/actions/runners --jq "
            f"'[.runners[]|select(.busy)]|length'\n"
            f"If the repair genuinely cannot wait, MESSAGE THE PEER SESSIONS FIRST "
            f"(ListAgents, then SendMessage) so the dead build is explained before they hunt it."
            + _escape("runner-busy-intended"))


# ---------------------------------------------------- a worktree path with no .git

#: Session 4e5b5e8f, 2026-08-26: `git worktree remove .wt-bs-auth` timed out half way (node_modules)
#: and had already deleted the worktree's `.git` link. The next `cd .wt-bs-auth && git checkout -B
#: … && git reset --hard origin/main` walked up to the MAIN checkout ~/dev/code/idp and discarded
#: its uncommitted tracked changes. The class: a git command aimed at a directory that is no
#: longer a worktree root silently acts on whichever repository contains it.
_SESSION_CWD: str | None = None


def _orphaned_dir(path: str) -> str | None:
    """`path` when it exists, has no .git entry, and git resolves it to a DIFFERENT toplevel."""
    if not path or not os.path.isdir(path):
        return None
    if os.path.lexists(os.path.join(path, ".git")):
        return None
    root = _worktree_root(path)
    if root and os.path.realpath(root) != os.path.realpath(path):
        return root
    return None


def orphan_state(cmd: str) -> dict | None:
    """Input for command.rego's orphaned_worktree rule: the `.wt-*`/worktrees dir this command
    targets (cd, -C or the session cwd) when it has no .git entry, and the checkout git would
    silently act on instead. Rego cannot stat, so the adapter answers that one question."""
    targets = [_expand(m.group("path").strip("'\""), cmd)
               for pat in (_LEADING_CD, _GIT_DASH_C) for m in pat.finditer(cmd)]
    for t in targets or ([_SESSION_CWD] if _SESSION_CWD else []):
        if not (os.path.basename(os.path.normpath(t)).startswith(".wt-") or "/worktrees/" in t):
            continue
        parent = _orphaned_dir(t)
        if parent:
            return {"dir": t, "parent": parent}
    return None


# ------------------------------------- discarding edits an earlier session made

#: Session 78caaa17, 2026-08-26 (crew#332): `git reset --hard` in ~/.estate discarded another
#: session's uncommitted REQUIREMENTS.jsonl edit. Nobody had run `git status` first, and the
#: file was older than the session that wiped it. The class: a command that throws away tracked
#: edits in a checkout where some of those edits predate this session, so they cannot be this
#: session's own and nobody has asked whose they are. The adapter answers the one question Rego
#: cannot -- "which modified tracked files here are older than this session" -- and Rego refuses.
_SESSION_STARTED: float | None = None

#: Seconds since this project's checkpoints/LATEST.md was written; None when there is nothing to
#: measure. Measured here, judged in policy/command.rego (crew#423 row 25, LAW 25).
_CHECKPOINT_AGE_S: int | None = None


def checkpoint_age_s(transcript_path: str | None) -> int | None:
    """Seconds since the project's checkpoints/LATEST.md was written; None when there is nothing to
    measure (crew#423 rows 16 and 25). None is BLIND, and the policy makes no verdict on it:
    - no transcript path: no project directory to look in;
    - no LATEST.md in the project: 3 of 8 active project dirs have never written one (#137 review),
      and a session that never wrote a checkpoint has not dropped a thread; a large number here was
      a refusal forever.
    A subagent's transcript sits at <project>/<session>/subagents/agent-*.jsonl, so the project
    directory is two levels up from there, not the subagents directory (#137 review: every subagent
    `git worktree add` was refused). The policy decides; this adapter only measures."""
    if not transcript_path:
        return None
    project = os.path.dirname(transcript_path)
    if os.path.basename(project) == "subagents":
        project = os.path.dirname(os.path.dirname(project))
    try:
        return int(time.time() - os.stat(os.path.join(project, "checkpoints", "LATEST.md")).st_mtime)
    except OSError:
        return None

_DISCARDS = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?(?:reset\s+(?:-\S+\s+)*--hard\b|checkout\s+(?:--\s|\.(?:\s|$)|-\s*-\s)"
    r"|restore\s(?!.*--staged)|clean\s+(?:-\S*f|--force))")


def _session_started(transcript_path: str | None) -> float | None:
    """When this session began: the transcript file's birth time (macOS), else its ctime."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    st = os.stat(transcript_path)
    return float(getattr(st, "st_birthtime", st.st_ctime))


def foreign_changes(cmd: str) -> dict | None:
    """Input for command.rego's foreign_changes rule: the modified tracked files in the checkout
    this command targets whose last write is OLDER than this session, when the command discards
    tracked edits and does not stash them first. Returns {"repo", "files"} or None."""
    if _SESSION_STARTED is None or not _DISCARDS.search(cmd) or re.search(r"\bgit\s+stash\b", cmd):
        return None
    targets = [_expand(m.group("path").strip("'\""), cmd)
               for pat in (_LEADING_CD, _GIT_DASH_C) for m in pat.finditer(cmd)]
    target = (targets or [_SESSION_CWD or ""])[-1]
    if not target or not os.path.isdir(target):
        return None
    try:
        out = subprocess.run([_real_tool("git"), "-C", target, "status", "--porcelain",
                              "--untracked-files=no"], capture_output=True, text=True, timeout=5)
        top = subprocess.run([_real_tool("git"), "-C", target, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not top:
        return None
    old = []
    for line in out.stdout.splitlines():
        if len(line) < 4 or line[1] not in "MD" and line[0] not in "MD":
            continue
        rel = line[3:].split(" -> ")[-1].strip('"')
        full = os.path.join(top, rel)
        if os.path.exists(full) and os.stat(full).st_mtime < _SESSION_STARTED:
            old.append(rel)
    return {"repo": top, "files": sorted(old)} if old else None


RULES = (rule_two_dot_diff, rule_pr_size, rule_runtime_state,
         rule_commit_in_shared_checkout, rule_merge_red_pr,
         rule_restart_kills_a_live_build)

#: Rules that let the command through and say something. Empty since 2026-08-17: the one warning
#: that lived here, the shared-checkout commit, was ignored for 105 commits and is a refusal now.
WARN_RULES: tuple = ()


# ------------------------------------------------------------- the Rego policy

#: Nine of the fifteen refusals are data in policy/command.rego now. `opa eval` answered
#: in 0.04s against rule-guard.py's 0.14-0.41s over 8 runs each, so this is not a tax.
POLICY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy")

#: Loading the directory means a new .rego file is live the moment it lands. Tests,
#: fixtures and this script are not policy, so they are not loaded as data -- the
#: fixtures in particular are conftest INPUTS and collide with each other as data.
_OPA_IGNORE = ("*_test.rego", "*.json", "*.py")

_OPA_QUERY = '{"deny": data.command.deny, "broken": data.command.broken}'


def normalise(cmd: str) -> str:
    """What every rule judges. Not the raw command.

    This function exists because on 2026-08-24 there were two of it. selftest() applied
    strip_commit_messages and main() did not, so `git commit -m 'never git add -A'` was
    asserted to pass by a green selftest and refused in production. A test that grades a
    different code path than the hook is not a test of the hook.
    """
    return strip_echo_payloads(strip_commit_messages(strip_heredocs(cmd)))


def opa_ask(cmd: str) -> tuple[list[str], list[str], str | None]:
    """Ask policy/*.rego about one command. Returns (denials, broken, error)."""
    opa = shutil.which("opa")
    if not opa:
        return [], [], "opa is not on PATH"
    argv = [opa, "eval", "--strict-builtin-errors", "--format", "json",
            "--data", POLICY_DIR, "--stdin-input", _OPA_QUERY]
    for pat in _OPA_IGNORE:
        argv[3:3] = ["--ignore", pat]
    try:
        out = subprocess.run(argv, input=json.dumps({"command": cmd, "arch": platform.machine(),
                                               "orphaned_worktree": orphan_state(cmd),
                                               "foreign_changes": foreign_changes(cmd),
                                               "checkpoint_age_s": _CHECKPOINT_AGE_S}),
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], [], f"opa eval did not run: {exc}"
    if out.returncode != 0:
        return [], [], f"opa eval exited {out.returncode}: {out.stderr.strip()[:400]}"
    try:
        v = json.loads(out.stdout)["result"][0]["expressions"][0]["value"]
    except (ValueError, KeyError, IndexError):
        return [], [], f"opa eval returned no verdict: {out.stdout.strip()[:200]}"
    return list(v.get("deny") or []), list(v.get("broken") or []), None


#: Rules whose answer depends on the tree this process is standing on, or on GitHub, rather
#: than on the command string. selftest() cannot judge them from a literal, so it names them
#: here and covers them separately against explicit inputs.
STATEFUL = ("rule_pr_size", "rule_commit_in_shared_checkout",
            "rule_merge_red_pr", "rule_restart_kills_a_live_build")


def decide(cmd: str, skip: tuple[str, ...] = ()) -> tuple[str, str] | None:
    """The single decision path: Rego first, then the Python rules Rego cannot express.

    Returns (source, message) for the first refusal, where source is "policy" or the rule's
    function name, or None to let the command through. main() and selftest() both call this,
    which is the whole point of it existing.
    """
    cmd = normalise(cmd)
    denials, broken, err = opa_ask(cmd)
    if broken:
        # A regex OPA cannot compile makes regex.match UNDEFINED, which makes the rule body
        # fail, which makes the rule PERMIT everything it was written to refuse -- and a
        # broken guard prints exactly what a clean run prints. So a broken policy refuses
        # rather than warns. It is a property of the file and not of the command, `opa test`
        # in CI catches it before it can ship, and the refusal names its own fix.
        return "policy", (
            "BLOCKED: the command policy disagrees with its own examples, so it cannot be "
            "trusted to refuse anything.\n" + "\n".join(broken)
            + "\n\nFix policy/command.rego, then:  "
              "opa test policy/command.rego policy/command_test.rego")
    if err:
        # Environmental, not a policy failure: OPA missing or unrunnable. Fail open like every
        # other path in this file, but say so on every single command until somebody fixes it.
        sys.stderr.write(f"[rule-guard] command policy NOT ENFORCED: {err}\n")
    if denials:
        return "policy", denials[0]
    for rule in RULES:
        if rule.__name__ in skip:
            continue
        try:
            reason = rule(cmd)
        except Exception:
            continue  # fail open, always
        if reason:
            return rule.__name__, reason
    return None



# ---------------------------------------------------------------- selftest

def selftest() -> int:
    # orphan_state both ways: a `.wt-*` dir with no .git inside a repo names its parent; a live
    # worktree (has .git) and the repo root give None. The refusal itself is Rego (opa test).
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo"); dead = os.path.join(repo, ".wt-dead"); live = os.path.join(repo, ".wt-live")
        os.makedirs(dead); os.makedirs(live)
        subprocess.run([_real_tool("git"), "init", "-q", repo], check=True, capture_output=True)
        open(os.path.join(live, ".git"), "w").write("gitdir: nowhere\n")
        for cmd, want in [(f"cd {dead} && git reset --hard origin/main", True),
                          (f"git -C {dead} checkout -B x origin/main", True),
                          (f"cd {live} && git status", False), (f"cd {repo} && git status", False)]:
            got = orphan_state(cmd) is not None
            print(f"  {'ok  ' if got == want else 'FAIL'}  orphan_state {'set' if want else 'unset'}: {cmd.replace(tmp, '<tmp>')}")
            if got != want:
                return 1
    # foreign_changes both ways: a tracked edit older than the session is named; the same edit
    # made after the session started, a stash in the same command, and a read-only command are
    # all None. The refusal itself is Rego (opa test).
    global _SESSION_STARTED
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo"); os.makedirs(repo)
        git = _real_tool("git")
        subprocess.run([git, "init", "-q", repo], check=True, capture_output=True)
        f = os.path.join(repo, "REQ.jsonl"); open(f, "w").write("a\n")
        subprocess.run([git, "-C", repo, "add", "REQ.jsonl"], check=True, capture_output=True)
        subprocess.run([git, "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
                       check=True, capture_output=True)
        open(f, "w").write("b\n"); os.utime(f, (1_000_000, 1_000_000))
        _SESSION_STARTED = 2_000_000.0
        for cmd, want in [(f"cd {repo} && git reset --hard origin/main", True),
                          (f"git -C {repo} checkout -- REQ.jsonl", True),
                          (f"cd {repo} && git stash && git reset --hard origin/main", False),
                          (f"cd {repo} && git status", False)]:
            got = foreign_changes(cmd) is not None
            print(f"  {'ok  ' if got == want else 'FAIL'}  foreign_changes {'set' if want else 'unset'}: {cmd.replace(tmp, '<tmp>')}")
            if got != want:
                return 1
        os.utime(f, (3_000_000, 3_000_000))
        got = foreign_changes(f"cd {repo} && git reset --hard") is not None
        print(f"  {'ok  ' if not got else 'FAIL'}  foreign_changes unset: edit newer than the session")
        if got:
            return 1
        _SESSION_STARTED = None
    cases = [
        ("gh workflow enable 337731742  # autoscale-intended", None),
        ("gh workflow disable 337731742", None),
        ("bash deploy/runners.sh scale 12", None),
        ("fly machine stop abc -a prospector-engine", None),
        ("git push --force origin b  # force-push-intended", None),
        ("git push --force-with-lease origin my-branch", None),
        ("git push --force-if-includes origin my-branch", None),
        ("git push origin my-branch", None),
        # Was None until 2026-08-24. A peer session added a direct-push-to-main refusal
        # (a110a9f) after an ungraded commit reached crew main; policy/command.rego
        # carries that decision, so the newer answer is the live one.
        ("git push --follow-tags origin main", "policy"),
        ("git push", None),
        ("grep -f patterns.txt file.txt", None),
        ("git stash pop  # stash-intended", None),
        ("git stash list", None),
        ("git stash show -p stash@{0}", None),
        ("git stash -u", None),
        ("git stash push -m wip", None),
        ("git add -A  # add-all-intended", None),
        ("git add -- scripts/ops_status.py", None),
        ("git add -p", None),
        ("git commit -m 'no-verify is bad'", None),
        ("git commit -m x\nrg -n PATTERN docs/", None),          # -n on a LATER line
        ("git commit -m x && tail -n 5 log", None),               # -n after a separator

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
        # A commit message quoting the rule is prose, not a command. This exact shape was
        # refused on 2026-08-19 while staging three explicit paths.
        ('git add -- CLAUDE.md docs/X.md && git commit -m "what stays: never git add -A here"',
         None),
        ("git commit -m 'the rule is: git add -A is banned'", None),
        ('git commit --message="never git add -A"', None),
        ("python3 - <<'PY'\nprint('the git add -A rule')\nPY\n", None),
        # crew#51: what echo or printf prints is text, not a command. The sentence that
        # explains a rule must not trip it; the command chained after it still must.
        ('echo "do not git add store/x.json" >> notes.md', None),
        ("printf 'git add -A is banned\\n' > a.txt", None),
        ('echo "prose" && git add store/x.json', "rule_runtime_state"),
        ("flyctl apps list", None),
        ("flyctl status -a prospector-store-web", None),
        ("flyctl logs -a prospector-engine", None),
        ("flyctl apps destroy prospector-engine --yes", None),
        ("flyctl scale count 0 -a x  # fly-revival-intended", None),
    ]
    bad = 0
    for cmd, want in cases:
        verdict = decide(cmd, skip=STATEFUL)
        got = verdict[0] if verdict else None
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

    # ~/.claude BECAME a git repository on 2026-08-21. A command run from there must still
    # resolve to the product tree. This case is only meaningful while that directory really is
    # a repo, so the precondition is checked out loud rather than silently making the check
    # unfailable -- an unfailable check is the estate's most repeated defect class.
    cfg = os.path.expanduser("~/.claude")
    if _worktree_root(cfg) != os.path.realpath(cfg):
        print("  NOTE  ~/.claude is not a git repo here, so the config-dir cases prove nothing")
    else:
        for cmd, cwd_, want in [
            ("gh pr create", cfg, REPO),
            (f"cd {cfg} && gh pr create", "/nonexistent", REPO),
            (f"cd {cfg}/ && gh pr create", "/nonexistent", REPO),
        ]:
            got = _repo_for(cmd, cwd_)
            if got != want:
                bad += 1
                print(f"  FAIL  config dir: _repo_for({cmd!r}, {cwd_!r}) -> {got}, wanted {want}")
            else:
                cases.append((cmd, want))
    # The exclusion is by IDENTITY, not by prefix. A worktree underneath the config dir is a
    # real tree and must resolve to itself; excluding the whole subtree would break it.
    for path_, want_ok in [(cfg, False), (cfg + "/worktrees/wt-a", True),
                           (cfg + "-other", True), (REPO, True), ("", False)]:
        if _is_product_repo(path_) != want_ok:
            bad += 1
            print(f"  FAIL  _is_product_repo({path_!r}) -> {not want_ok}, wanted {want_ok}")
        else:
            cases.append((f"_is_product_repo({path_})", want_ok))

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
    # A machine repair while a runner is mid-job. The busy lookup is stubbed, because a rule
    # that can only be proved when CI happens to be busy is a rule that is never proved.
    _real_busy = _busy_runners
    for name, busy, cmd, want_block in [
        ("busy_fleet_blocks_update", ["runner-7819644f116928"],
         'fly machine update abc -a prospector-ci --standby-for "" --yes', True),
        ("busy_fleet_blocks_restart", ["r1"], "fly machine restart abc -a prospector-ci", True),
        ("busy_fleet_blocks_destroy", ["r1"], "fly machine destroy abc -a hermes-ci", True),
        ("idle_fleet_allows_update", [],
         'fly machine update abc -a prospector-ci --standby-for "" --yes', False),
        # Starting a stopped machine cannot interrupt a build, so it is never this rule's business.
        ("start_is_never_blocked", ["r1"], "fly machine start abc -a prospector-ci", False),
        # An app that is not a runner fleet has no jobs to destroy.
        ("non_runner_app_allowed", ["r1"], "fly machine restart abc -a prospector-engine", False),
        ("escape_hatch_allows", ["r1"],
         "fly machine restart abc -a prospector-ci  # runner-busy-intended", False),
    ]:
        globals()["_busy_runners"] = lambda _repo, _b=busy: list(_b)
        got = bool(rule_restart_kills_a_live_build(cmd))
        if got != want_block:
            bad += 1
            print(f"  FAIL  {name}: wanted block={want_block}, got {got}")
        else:
            cases.append((name, True))
    globals()["_busy_runners"] = _real_busy

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


_COMMIT_MSG = re.compile(r"""(-m|--message|--body|--title|--caption)(=|\s+)(?P<q>['"])(?P<body>.*?)(?<!\\)(?P=q)""",
                         re.DOTALL)


_ECHO_PAYLOAD = re.compile(r"""\b(echo|printf)(\s+-[a-zA-Z]+)*\s+(?P<q>['"])(?P<body>.*?)(?<!\\)(?P=q)""",
                           re.DOTALL)


def strip_echo_payloads(cmd: str) -> str:
    """Drop the quoted argument of `echo` and `printf` before the rules judge a command.

    crew#51, found 2026-08-23 while wiring ticket-gate.py: `echo "do not run git push"` was
    read as a push and refused. What echo prints is text the shell never executes, exactly
    like a heredoc body or a commit message, and a guard that refuses the sentence that
    explains it is a guard people learn to bypass.

    Only the quoted argument goes; the echo itself, any redirect after it, and anything
    chained with && or ; are still judged. An unquoted payload is left alone: it is one
    shell word per token and a guarded verb in it is as likely a mistake as prose.
    """
    return _ECHO_PAYLOAD.sub(lambda m: f"{m.group(1)}{m.group(2) or ''} {m.group('q')}{m.group('q')}", cmd)


def strip_commit_messages(cmd: str) -> str:
    """Drop `-m "..."` bodies before the rules judge a command.

    Same reason as strip_heredocs, and found the same way: on 2026-08-19 this guard refused
    `git add -- CLAUDE.md .claude/skills docs/... && git commit -m "... never git add -A ..."`.
    The staged paths were explicit. The only match was the rule being QUOTED in the message that
    explains it.

    A commit message is text. It cannot execute, so nothing is lost by not judging it, and a
    guard that blocks writing down its own rule is a guard people learn to bypass.

    Only the quoted body goes. `git commit -m` with an unquoted word is left alone, and so is
    everything outside the quotes -- including anything chained after the commit with && or ;.
    """
    return _COMMIT_MSG.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group('q')}{m.group('q')}", cmd)


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
    global _ACTIVE_REPO, _SESSION_CWD, _SESSION_STARTED, _CHECKPOINT_AGE_S
    _SESSION_CWD = payload.get("cwd")
    _SESSION_STARTED = _session_started(payload.get("transcript_path"))
    _CHECKPOINT_AGE_S = checkpoint_age_s(payload.get("transcript_path"))
    _ACTIVE_REPO = _repo_for(cmd, payload.get("cwd"))
    verdict = decide(cmd)
    if verdict:
        sys.stderr.write(verdict[1] + "\n")
        return 2
    cmd = normalise(cmd)
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
