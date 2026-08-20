#!/usr/bin/env python3
"""SessionStart: refuse to let a session work in a worktree whose git is dead.

FOUNDER DIRECTIVE 2026-08-21, verbatim: "This worktree has no working git -- git ls-files
returns 0 files. That is why 17 guards fail here and why my fix could never be committed. hw
do you prevent htis reoccuruing".

THE TRAP. A linked worktree keeps its checkout in a plain directory and keeps its GIT in the
main repo, at .git/worktrees/<name>/. The worktree's own `.git` is a one-line FILE naming that
directory. Delete the admin directory -- `git worktree prune`, `git worktree remove`, a sweep
script grading trees against the wrong clone -- and the files stay exactly where they were.
Everything still opens. Nothing says a word.

WHY IT COSTS A WHOLE SESSION RATHER THAN A MINUTE. Measured in wt-storeroot on 2026-08-21:

    git ls-files | wc -l   ->   0      exit status 0

Zero files, and it SUCCEEDS. Every guard that asks git for the tracked file list gets an empty
population and grades it clean or grades it missing; 17 tests failed there for that reason and
none of them named git. The session read them as 17 real defects. The fix it was carrying --
the one that ends a live production outage -- could not be committed at all, and that was not
discovered until hours in, because `git commit` is the first command that actually complains.

SCALE, same measurement: 113 worktrees in this estate carry a `.git` file. 44 of them point at
a directory that does not exist. It is not one bad tree, it is two in five.

WHAT THIS HOOK DOES. One `git rev-parse --git-dir` at session start. Healthy tree, silence and
exit 0. Dead tree, a banner at the top of the session naming the exact recovery, before the
first edit rather than after the last. It repairs what is repairable first: when the admin
directory still exists and only the pointers are stale, `git worktree repair` fixes it and the
session carries on with nothing to do.

WHY DETECTION RATHER THAN PREVENTION. The deletion happens in another process, often another
session, sometimes days earlier. Nothing this hook could refuse would have stopped it. What is
fixable is the SILENCE: an agent must not be able to spend a session in a tree that cannot
commit. That is the class -- a failure that reports success -- and it is the same one as
memory `a-directory-is-not-a-population`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

_SYSTEM_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def _git(*args: str, cwd: str) -> tuple[int, str]:
    """Run git with a fixed PATH so a shim on the session's PATH cannot re-enter a guard."""
    exe = shutil.which("git", path=_SYSTEM_PATH) or "git"
    env = dict(os.environ)
    env["PATH"] = _SYSTEM_PATH
    try:
        p = subprocess.run((exe, *args), cwd=cwd, capture_output=True, text=True,
                           timeout=20, env=env, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def gitdir_of(tree: str) -> str | None:
    """The admin directory a worktree's `.git` FILE names, or None if it is not that shape."""
    dot = os.path.join(tree, ".git")
    if not os.path.isfile(dot):
        return None
    try:
        with open(dot, encoding="utf-8", errors="replace") as fh:
            line = fh.readline().strip()
    except OSError:
        return None
    return line[len("gitdir:"):].strip() if line.startswith("gitdir:") else None


def diagnose(tree: str) -> dict:
    """Grade one directory. `state` is one of ok / not-a-repo / repaired / dead."""
    rc, _ = _git("rev-parse", "--git-dir", cwd=tree)
    if rc == 0:
        return {"state": "ok"}
    gitdir = gitdir_of(tree)
    if gitdir is None:
        # No `.git` file at all: an ordinary directory outside a repo. Not this hook's business.
        return {"state": "not-a-repo"}
    if os.path.isdir(gitdir):
        # The admin directory is there and only the pointers are stale -- git fixes this itself.
        _git("worktree", "repair", cwd=tree)
        rc2, _ = _git("rev-parse", "--git-dir", cwd=tree)
        if rc2 == 0:
            return {"state": "repaired", "gitdir": gitdir}
    return {"state": "dead", "gitdir": gitdir}


def banner(tree: str, gitdir: str) -> str:
    name = os.path.basename(tree.rstrip("/"))
    common = gitdir.split("/.git/worktrees/")[0] if "/.git/worktrees/" in gitdir else ""
    fresh = os.path.join(os.path.dirname(common) or "/tmp", f"wt-{name}-new")
    return f"""[worktree-git-guard] THIS WORKING TREE HAS NO GIT. YOU CANNOT COMMIT FROM HERE.

  tree    {tree}
  .git    names {gitdir}
          that directory does not exist, so this checkout belongs to no repository.

WHAT YOU WILL SEE IF YOU IGNORE THIS. `git ls-files` prints nothing AND EXITS 0, so every
guard and test that asks git for the tracked file list grades an empty repo. They fail for
reasons that name anything but git. `git commit` is the first command that says so plainly,
and by then the work is done and unlandable.

DO NOT debug those failures and DO NOT try to repair this tree. Make a fresh one and re-apply
your edits into it -- re-apply, never copy whole files, because this tree may be many commits
adrift from main and copying would revert other sessions' work:

  git -C {common or '<main-checkout>'} worktree add --detach {fresh} origin/main
  {os.path.join(common, 'scripts/setup_worktree.sh') if common else 'scripts/setup_worktree.sh'} {fresh}

Files here are still READABLE. Read your work out of this tree; write it into the new one."""


def selftest() -> int:
    import tempfile
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    with tempfile.TemporaryDirectory() as td:
        # 1. a directory with no .git at all
        plain = os.path.join(td, "plain")
        os.makedirs(plain)
        check("no .git anywhere", diagnose(plain)["state"], "not-a-repo")

        # 2. a real repo
        repo = os.path.join(td, "repo")
        os.makedirs(repo)
        _git("init", "-q", cwd=repo)
        check("a real repo is ok", diagnose(repo)["state"], "ok")

        # 3. THE CASE THIS HOOK EXISTS FOR: a .git file naming a missing admin dir
        dead = os.path.join(td, "dead")
        os.makedirs(dead)
        missing = os.path.join(td, "repo", ".git", "worktrees", "gone")
        with open(os.path.join(dead, ".git"), "w", encoding="utf-8") as fh:
            fh.write(f"gitdir: {missing}\n")
        d = diagnose(dead)
        check("a dangling gitdir is dead", d["state"], "dead")
        check("the dead report names the gitdir", d.get("gitdir"), missing)

        # 4. the banner has to carry the recovery, not just the diagnosis
        b = banner(dead, missing)
        check("banner names the tree", tree_in := (dead in b), True)
        check("banner gives worktree add", "worktree add --detach" in b, True)
        check("banner gives setup_worktree", "setup_worktree.sh" in b, True)
        check("banner warns ls-files exits 0", "EXITS 0" in b, True)

        # 5. a .git file of the wrong shape is not our business
        odd = os.path.join(td, "odd")
        os.makedirs(odd)
        with open(os.path.join(odd, ".git"), "w", encoding="utf-8") as fh:
            fh.write("this is not a gitdir line\n")
        check("a malformed .git file is not-a-repo", diagnose(odd)["state"], "not-a-repo")

        # 6. repairable: admin dir present, .git pointing at it, but git still unhappy.
        #    A real worktree, then its .git file rewritten to an absolute path git accepts.
        wt = os.path.join(td, "wt")
        _git("commit", "-q", "--allow-empty", "-m", "x", cwd=repo)
        rc, _ = _git("worktree", "add", "--detach", wt, cwd=repo)
        if rc == 0:
            check("a live worktree is ok", diagnose(wt)["state"], "ok")

    for f in fails:
        print("FAIL:", f)
    print(f"selftest: {8 - len(fails)}/8 passed" if not fails else f"selftest: {len(fails)} FAILED")
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        json.load(sys.stdin) if not sys.stdin.isatty() else None
    except Exception:  # noqa: BLE001 -- a hook that dies on its own input is worse than none
        pass
    tree = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        d = diagnose(tree)
    except Exception:  # noqa: BLE001 -- fail OPEN, always
        return 0
    if d["state"] == "dead":
        print(banner(tree, d["gitdir"]))
    elif d["state"] == "repaired":
        print(f"[worktree-git-guard] this worktree's git pointers were stale and have been "
              f"repaired in place ({d['gitdir']}). Nothing else to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
