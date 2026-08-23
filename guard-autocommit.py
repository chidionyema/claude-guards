#!/usr/bin/env python3
"""Stop hook: never let the enforcement layer sit uncommitted again.

THE CLASS THIS CLOSES, measured twice in 48 hours:
  2026-08-19  b95e629 "commit the six uncommitted guards and five drifted ones"
  2026-08-21  2a44811 17 guards uncommitted -- 12 modified carrying 696 insertions,
              plus 5 that git had NEVER seen (1489 lines). No remote. No restore point.

Nobody owns committing ~/.claude/scripts. It is edited by every session on this machine
(push-pr-fence.py by 5 concurrent sessions, rule-guard.py by 3), and a shared file with
no owner is a file that drifts. A memory file cannot fix that -- the next session has not
read it, and the session after that edits a different guard. So this is self-healing
(LAW 6 rung 1), not a guard and not a note: it runs at the end of EVERY turn of EVERY
session, so the layer is never more than one turn away from a restore point.

DESIGN RULES, each one paid for:
  * FAIL OPEN, ALWAYS. This must never block a session from finishing. Every failure
    path returns 0. A backup mechanism that can stop work will be turned off.
  * EXPLICIT PATHS, never a blanket stage. rule-guard.py refuses `add -A` in this estate
    and is right to: it would sweep in backups like memory-loop.py.before-law16-cap.
  * PARSE BEFORE COMMIT. A guard captured mid-edit that cannot be imported is worse than
    no snapshot, because it looks like a restore point and is not one. Non-parsing files
    are left for the next turn, which is seconds away.
  * ONE WRITER. Five sessions ending a turn at once means five `git commit` calls on one
    index. The lock is os.link(), the only atomically create-only-if-absent call there is,
    with a TTL because a hook is a short-lived subprocess whose pid is dead immediately
    after it writes -- a liveness check would hand the lock to everyone.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path.home() / ".claude" / "scripts"
LOCK_TTL = 120          # seconds; a commit takes well under a second
PUSH_EVERY = 300        # push at most once every 5 min; commits are always immediate
KEEP_EXT = {".py", ".sh"}


def git(repo: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except Exception as exc:
        return 1, str(exc)


def acquire(repo: Path) -> Path | None:
    """os.link is the only atomic create-if-absent. TTL expiry, never liveness."""
    lock = repo / ".git" / "autocommit.lock"
    tmp = repo / ".git" / f"autocommit.{os.getpid()}.tmp"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > LOCK_TTL:
            lock.unlink(missing_ok=True)
        tmp.write_text(str(os.getpid()))
        os.link(tmp, lock)
        return lock
    except FileExistsError:
        return None
    except Exception:
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def candidates(repo: Path) -> tuple[list[str], list[str]]:
    """(committable, skipped) -- source files only, and only ones that still parse."""
    rc, out = git(repo, "status", "--porcelain")
    if rc != 0:
        return [], []
    good: list[str] = []
    bad: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:                       # a rename; take the destination
            path = path.split(" -> ")[-1]
        if Path(path).suffix not in KEEP_EXT:    # excludes .before-law16-cap backups
            continue
        full = repo / path
        if not full.exists():                    # deletions are a human decision
            continue
        if full.suffix == ".py":
            try:
                ast.parse(full.read_text(errors="replace"))
            except SyntaxError:
                bad.append(path)                 # mid-edit; next turn will get it
                continue
        good.append(path)
    return good, bad


def commit(repo: Path, files: list[str], skipped: list[str], session: str) -> bool:
    rc, _ = git(repo, "add", "--", *files)
    if rc != 0:
        return False
    body = ["chore(guards): autocommit %d changed guard%s"
            % (len(files), "" if len(files) == 1 else "s"), "",
            "Written by guard-autocommit.py at the end of a session turn, because this",
            "directory is edited by every session and owned by none. Twice in 48 hours it",
            "had drifted with no restore point (b95e629, 2a44811); this makes that",
            "impossible rather than unlikely.", ""]
    body += ["  " + f for f in sorted(files)[:40]]
    if len(files) > 40:
        body.append("  ... and %d more" % (len(files) - 40))
    if skipped:
        body += ["", "Left for the next turn (did not parse, so probably mid-edit):"]
        body += ["  " + f for f in sorted(skipped)[:10]]
    body += ["", "session: " + session]
    rc, _ = git(repo, "-c", "user.name=guard-autocommit",
                "-c", "user.email=chidionyema@gmail.com",
                "commit", "-m", "\n".join(body))
    return rc == 0


def maybe_push(repo: Path) -> str:
    stamp = repo / ".git" / "autocommit.lastpush"
    try:
        if stamp.exists() and time.time() - stamp.stat().st_mtime < PUSH_EVERY:
            return "throttled"
    except Exception:
        pass
    rc, _ = git(repo, "remote")
    if rc != 0:
        return "no remote"
    rc, out = git(repo, "push", "origin", "HEAD", timeout=45)
    try:
        stamp.write_text(str(time.time()))
    except Exception:
        try: (__import__("sys").path.append(__import__("os").path.expanduser("~/.claude/scripts")), __import__("guard_report").broken(__file__, 139))
        except Exception: pass
    return "pushed" if rc == 0 else "push failed (local commit is safe)"


def run(repo: Path, session: str = "unknown") -> str:
    if not (repo / ".git").exists():
        return "not a repo"
    files, skipped = candidates(repo)
    if not files:
        return "nothing to commit" + (" (%d unparseable)" % len(skipped) if skipped else "")
    lock = acquire(repo)
    if lock is None:
        return "another session holds the lock"
    try:
        if not commit(repo, files, skipped, session):
            return "commit failed"
        return "committed %d: %s" % (len(files), maybe_push(repo))
    finally:
        try:
            lock.unlink(missing_ok=True)
        except Exception:
            pass


def selftest() -> int:
    import shutil, tempfile
    fails: list[str] = []
    total = [0]

    def check(name, cond, detail=""):
        total[0] += 1
        print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  <- " + detail))
        if not cond:
            fails.append(name)

    tmp = Path(tempfile.mkdtemp())
    try:
        r = tmp / "guards"
        r.mkdir()
        git(r.parent, "init", "-q", str(r))
        (r / "good.py").write_text("x = 1\n")
        git(r, "add", "--", "good.py")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
        before = git(r, "rev-list", "--count", "HEAD")[1].strip()

        (r / "good.py").write_text("x = 2\n")
        (r / "brand-new.py").write_text("y = 3\n")
        (r / "helper.sh").write_text("echo hi\n")
        (r / "broken.py").write_text("def f(:\n")
        (r / "backup.py.before-law16-cap").write_text("z = 4\n")

        good, bad = candidates(r)
        check("a modified guard is picked up", "good.py" in good, str(good))
        check("a guard git has never seen is picked up", "brand-new.py" in good, str(good))
        check("shell guards count too", "helper.sh" in good, str(good))
        check("a guard that does not parse is NOT committed", "broken.py" not in good, str(good))
        check("the unparseable one is reported, not silently dropped", "broken.py" in bad, str(bad))
        check("a .before-* backup is never swept in",
              not any("before-law16" in f for f in good), str(good))

        msg = run(r, session="selftest")
        after = git(r, "rev-list", "--count", "HEAD")[1].strip()
        check("it actually commits", int(after) == int(before) + 1, f"{before}->{after} {msg}")
        check("the tree is clean afterwards except the excluded files",
              set(l[3:] for l in git(r, "status", "--porcelain")[1].splitlines())
              == {"broken.py", "backup.py.before-law16-cap"},
              git(r, "status", "--porcelain")[1].replace("\n", " | "))
        check("the commit names the session",
              "selftest" in git(r, "log", "-1", "--format=%B")[1], "")

        check("a second run with nothing to do is a no-op",
              run(r, "x") .startswith("nothing to commit"), run(r, "x"))

        # concurrency: a held lock must make the next caller stand down, not double-commit
        (r / "good.py").write_text("x = 9\n")
        held = acquire(r)
        check("os.link lock is exclusive", held is not None, "first acquire failed")
        check("a second session stands down rather than racing the index",
              acquire(r) is None, "two writers on one git index")
        n_before = git(r, "rev-list", "--count", "HEAD")[1].strip()
        check("a locked-out run commits nothing",
              run(r, "y") == "another session holds the lock"
              and git(r, "rev-list", "--count", "HEAD")[1].strip() == n_before, "")
        if held:
            held.unlink(missing_ok=True)

        # a stale lock must expire -- it belongs to a session, and hooks are short-lived
        stale = acquire(r)
        os.utime(stale, (time.time() - LOCK_TTL - 30,) * 2)
        check("a lock older than the TTL is reclaimed", acquire(r) is not None,
              "a dead session would wedge every future turn")
        (r / ".git" / "autocommit.lock").unlink(missing_ok=True)

        # fail open, always
        check("a non-repo directory is survived, never raised",
              run(tmp / "nope") == "not a repo", "")
        broken_repo = tmp / "brk"
        broken_repo.mkdir()
        (broken_repo / ".git").write_text("gitdir: /nowhere/at/all")
        out = run(broken_repo)
        check("a corrupt repo fails open with a message, not a traceback",
              isinstance(out, str), out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # counted, never hardcoded: a hardcoded total reports 15/15 while running 16 checks,
    # and the one it silently stops counting is the one nobody notices is gone.
    print(("\n%d/%d checks pass" % (total[0] - len(fails), total[0])) if not fails
          else "\nFAILED %d of %d: %s" % (len(fails), total[0], ", ".join(fails)))
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    session = "unknown"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        session = str(payload.get("session_id") or "unknown")[:12]
    except Exception:
        pass
    if "--verbose" in sys.argv:
        print(run(REPO, session), file=sys.stderr)
    else:
        try:
            run(REPO, session)
        except Exception:
            pass          # FAIL OPEN. A backup that blocks a turn gets switched off.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
