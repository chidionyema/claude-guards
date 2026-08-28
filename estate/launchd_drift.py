#!/usr/bin/env python3
"""Find launchd jobs whose loaded definition points at code nobody published.

Two classes, one symptom: the job reports exit 0 while running the wrong code.

  GONE    the path in the loaded definition no longer exists.
  PARKED  the path exists, but it sits in a git checkout standing on some
          session's feature branch, so the job runs whatever that session
          left behind.

Why this exists. launchctl runs the definition it loaded at bootstrap, not the
plist sitting on disk. A `git mv` of a script leaves a job whose plist is
correct and whose behaviour is broken, and `launchctl list` reports the LAST
exit code, so a job whose program no longer exists shows 0 with empty stderr
and reads as healthy forever.

Measured 2026-08-22 on this machine: com.estate.costsentinel and
com.estate.downshift had both been on a stale loaded definition since 13:07.
downshift, the spend brake, reported exit 0 and had not run once. Against a
measured $6,048 in seven days versus a $120/day cap, the money brake was off
and every instrument said it was on.

PARKED, measured 2026-08-24 on this machine: 10 of 10 scheduled jobs whose
program lives in a shared checkout, 8 of them on a feature branch. The one
that cost something was com.founder.estatesnapshot: I left ~/dev/code/crew on
feat/mature-platform-gate, the hourly snapshot correctly refused to publish to
a stranded branch, and STATE.md - the estate's single source of truth - went
3.9 hours stale on main while every instrument read healthy.

The fix for PARKED is a dedicated worktree pinned to the published branch, so
the job owns its checkout and no human session can move it.

Read-only. Prints what it finds and exits 1 when anything is stale, so it can
gate a move or run on a schedule. The fix it prints is the whole fix.
"""
import os
import re
import subprocess
import sys

UID = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
# Any absolute path with a script extension. An earlier cut allowlisted
# /Users, /opt and /usr/local, and a deliberately broken test job under
# /tmp walked straight past it. A guard that can only see where it was
# told to look is a guard that reports clean.
PATH_RE = re.compile(r"/[^\s\"',]+\.(?:py|sh|rb|js|pl)\b")


def loaded_labels():
    """Every loaded job label that is not Apple's own."""
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    labels = []
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        label = parts[2].strip()
        if label and not label.startswith("com.apple"):
            labels.append(label)
    return labels


def loaded_workdir(label):
    """The working directory in the definition launchd holds, or "".

    Read because a job's code does not have to arrive through a path with a
    script extension. ai.estate.idp's whole loaded definition names one file,
    hc-wrap.sh, and runs `idp-up` out of its working directory. Grading only
    the extension-bearing paths graded the wrapper and never the payload,
    which is grading a proxy.
    """
    try:
        out = subprocess.run(
            ["launchctl", "print", f"gui/{UID}/{label}"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except subprocess.TimeoutExpired:
        return ""
    for line in out.splitlines():
        if "working directory =" in line:
            return line.split("=", 1)[1].strip()
    return ""


def loaded_paths(label):
    """Script paths inside the definition launchd actually holds in memory."""
    try:
        out = subprocess.run(
            ["launchctl", "print", f"gui/{UID}/{label}"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except subprocess.TimeoutExpired:
        return None
    return sorted(set(PATH_RE.findall(out)))


# Jobs whose whole purpose IS to inspect the live working checkout. Pinning
# these to a published branch would make them grade a tree nobody edits, which
# is a guard that refuses correct work (LAW 38). Every entry carries its reason.
# Anything NOT listed here is graded. An unknown job is never silently exempt.
LIVE_TREE_OK = {
    "com.chidionyema.guard-selftest":
        "runs every guard's selftest against the scripts as they are being edited",
    "ai.estate.tracked-guard":
        "grades uncommitted work in the live checkout; a pinned tree has none",
}


def repo_of(path):
    """The git checkout a path sits in, or "" if it is not in one."""
    d = path if os.path.isdir(path) else os.path.dirname(path)
    rc = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                        capture_output=True, text=True)
    return rc.stdout.strip() if rc.returncode == 0 else ""


def published_branch(repo):
    """The branch this repo's work is supposed to reach, or "" if unknowable.

    Returning "" is not a pass. A repo whose published branch cannot be read is
    reported as unprovable, because a guard that loses its evidence reports
    BLIND and never a verdict.
    """
    out = subprocess.run(["git", "-C", repo, "symbolic-ref", "-q",
                          "refs/remotes/origin/HEAD"],
                         capture_output=True, text=True).stdout.strip()
    if out:
        return out.rsplit("/", 1)[-1]
    for cand in ("main", "master"):
        rc = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "-q",
                             "refs/remotes/origin/" + cand],
                            capture_output=True, text=True)
        if rc.returncode == 0:
            return cand
    return ""


def parked(label, paths, workdir=""):
    """Every (repo, on, want) this job runs out of a parked checkout.

    Every, not the first. An earlier cut returned on the first hit and
    ai.estate.idp reported ~/.claude/scripts while hiding that ~/dev/code/idp
    was on fix/catalog-litellm-langfuse. A job can draw code from more than one
    checkout and each one can be parked independently.
    """
    if label in LIVE_TREE_OK:
        return []
    hits, seen = [], set()
    for path in list(paths) + ([workdir] if workdir else []):
        repo = repo_of(path if os.path.isdir(path) else os.path.dirname(path) or path)
        if not repo or repo in seen:
            continue
        seen.add(repo)
        want = published_branch(repo)
        on = subprocess.run(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
        if not want:
            hits.append((repo, on or "?", ""))
        elif on == "HEAD" and _at_published_tip(repo, want):
            # A detached HEAD sitting exactly on origin/<want> is the estate's
            # pinned shape (the shared idp and crew checkouts are moved with
            # `git checkout --detach origin/main` so a peer's branch never hides
            # merged rows). It is not parked; only a detached HEAD that has
            # drifted from that tip is. Reported 2026-08-28 as 38 holes.
            continue
        elif on != want:
            hits.append((repo, on, want))
    return hits


def _at_published_tip(repo, want):
    """True when HEAD is the same commit as refs/remotes/origin/<want>."""
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    tip = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "-q",
                          "refs/remotes/origin/" + want],
                         capture_output=True, text=True).stdout.strip()
    return bool(head) and head == tip


def selftest():
    """Prove the PARKED check both ways in one run: it flags a parked checkout
    AND it passes a pinned one. A guard only ever seen refusing has never been
    shown to permit, and a guard that refuses correct work is an outage."""
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        origin = os.path.join(tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
        for name, branch, want_flag in (("pinned", "main", False),
                                        ("parked", "feat/left-behind", True)):
            repo = os.path.join(tmp, name)
            subprocess.run(["git", "clone", "-q", origin, repo], check=True)
            g = ["git", "-C", repo]
            subprocess.run(g + ["config", "user.email", "t@t"], check=True)
            subprocess.run(g + ["config", "user.name", "t"], check=True)
            script = os.path.join(repo, "job.py")
            if not os.path.exists(script):
                # the second clone already has it from origin
                open(script, "w").write("#!/usr/bin/env python3\n")
                subprocess.run(g + ["add", "job.py"], check=True)
                subprocess.run(g + ["commit", "-qm", "job"], check=True)
                subprocess.run(g + ["push", "-q", "origin", "main"], check=True)
            if branch != "main":
                subprocess.run(g + ["checkout", "-qb", branch], check=True)
            hits = parked("test.job", [script])
            if bool(hits) != want_flag:
                fails.append(f"{name} on '{branch}': expected "
                             f"{'a flag' if want_flag else 'no flag'}, got {hits!r}")
            elif want_flag:
                _, on, wanted = hits[0]
                if (on, wanted) != (branch, "main"):
                    fails.append(f"parked: reported on={on!r} want={wanted!r}")
            if name == "parked":
                # the working directory is graded even when no script path is
                # in it, which is how ai.estate.idp was being missed
                if not parked("test.job", [], repo):
                    fails.append("a parked working directory with no script "
                                 "path in it was not flagged")
                # both checkouts are reported, not just the first
                pinned_script = os.path.join(tmp, "pinned", "job.py")
                both = parked("test.job", [pinned_script], repo)
                if len(both) != 1 or both[0][1] != branch:
                    fails.append(f"expected the parked repo reported alongside "
                                 f"the pinned one, got {both!r}")
        # detached exactly at origin/main is pinned, not parked; one commit
        # past it is parked again (2026-08-28: 38 holes were this shape)
        det = os.path.join(tmp, "detached")
        subprocess.run(["git", "clone", "-q", origin, det], check=True)
        gd = ["git", "-C", det]
        subprocess.run(gd + ["config", "user.email", "t@t"], check=True)
        subprocess.run(gd + ["config", "user.name", "t"], check=True)
        subprocess.run(gd + ["checkout", "-q", "--detach", "origin/main"], check=True)
        if parked("test.job", [os.path.join(det, "job.py")]):
            fails.append("a detached HEAD at origin/main was flagged as parked")
        subprocess.run(gd + ["commit", "-q", "--allow-empty", "-m", "drift"], check=True)
        drifted = parked("test.job", [os.path.join(det, "job.py")])
        if not drifted or drifted[0][1] != "HEAD":
            fails.append(f"a detached HEAD past origin/main was not flagged: {drifted!r}")
        # a listed job is exempt, and only a listed one
        if parked("ai.estate.tracked-guard", [script]):
            fails.append("allowlisted label was still graded")
    if fails:
        for f in fails:
            print("SELFTEST FAIL:", f)
        return 1
    print("selftest OK: PARKED flags a checkout on 'feat/left-behind', passes one on "
          "'main', grades a working directory with no script path in it, reports "
          "every parked checkout a job draws from, and exempts only the listed labels")
    return 0


def main():
    stale = []
    drifted = []
    unreadable = []
    checked = 0
    for label in loaded_labels():
        paths = loaded_paths(label)
        if paths is None:
            unreadable.append(label)
            continue
        checked += 1
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            stale.append((label, missing))
            continue
        for hit in parked(label, paths, loaded_workdir(label)):
            drifted.append((label, hit))

    print(f"checked {checked} loaded jobs")
    if unreadable:
        print(f"could not read {len(unreadable)}: {', '.join(unreadable)}")

    if not stale and not drifted:
        print("no drift: every loaded definition points at published code "
              "on a path that exists")
        return 0

    print(f"\nSTALE: {len(stale)} job(s) run a definition naming a path that is gone.")
    print("launchctl list will still report the old exit code for these.\n")
    for label, missing in stale:
        print(f"  {label}")
        for p in missing:
            print(f"      MISSING {p}")
        print(f"      fix: launchctl bootout gui/{UID}/{label} && "
              f"launchctl bootstrap gui/{UID} ~/Library/LaunchAgents/{label}.plist")

    if drifted:
        print(f"\nPARKED: {len(drifted)} job(s) run code out of a checkout a "
              f"session can move.")
        print("These report exit 0 while running whatever branch was left behind.\n")
        for label, (repo, on, want) in drifted:
            if not want:
                print(f"  {label}")
                print(f"      UNPROVABLE {repo} on '{on}': no published branch "
                      f"to compare against")
                continue
            print(f"  {label}")
            print(f"      PARKED {repo} is on '{on}', not '{want}'")
            print(f"      fix: give the job its own worktree pinned to {want} and "
                  f"point WorkingDirectory at it:")
            print(f"           git -C {repo} worktree add <runtime-path> {want}")
    return 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
