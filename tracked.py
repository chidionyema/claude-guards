#!/usr/bin/env python3
"""LAW 24: if it is load-bearing, it is in git.

Files this estate depends on live outside any repository. A scheduled job, the
laws, the settings that wire up every session. Any of them can be changed by an
agent with no record but a chat transcript. This tracks copies of them here and
fails when the copy and the live file drift apart.

    tracked.py --check    exit 1 on any difference. For CI and for any agent
                          about to trust the committed copy.
    tracked.py --pull     bring the live files in so the difference can be
                          committed.
    tracked.py --sync     pull, commit and push, with no person involved.
                          This is what the scheduled job runs. LAW 31: the
                          founder does not run scripts.

A stale copy is worse than none, because it reads as a record. That is what
--check is for.

LAW 21 outranks this and is enforced here rather than trusted. Every file is
scanned before it is copied in, and one that looks like it holds a credential is
refused, named, and left out. Directories that exist only to hold keys are not
listed at all -- they are in rebuild/PREREQUISITES.md, which records that they
must exist and what for, and never what is in them.
"""
import argparse, filecmp, fnmatch, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "tracked.json")


HOME = os.path.expanduser("~")


def entries(into=None):
    """into=DIR aims every live path at a throwaway home instead of this one.

    That is what makes the rebuild drill runnable without an admin password and
    without a second user account. A drill you cannot run is the reason this one
    had never been run (LAW 19: an exit that has never been drilled is a hope)."""
    for e in json.load(open(MANIFEST)):
        live = os.path.expanduser(e["live"])
        if into:
            live = os.path.join(into, os.path.relpath(live, HOME)) \
                if live.startswith(HOME + os.sep) else live
        e["live"] = live
        e["repo_abs"] = os.path.join(HERE, e["repo"])
        yield e


# Enough to catch a key pasted into a config file. It does not have to be
# clever, only refuse rather than pass when it is unsure.
SECRET = re.compile(
    r"(sk-ant-|sk-proj-|sk-[A-Za-z0-9]{20,}|ghp_|gho_|ghu_|ghs_|github_pat_"
    r"|xox[baprs]-|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|AIza[0-9A-Za-z_-]{30,}|\b\d{8,10}:[A-Za-z0-9_-]{35}\b"
    r"|AGE-SECRET-KEY-1|<RSAKeyValue>"
    r'''|["']?(api[_-]?key|secret|password|token)["']?\s*[:=]\s*["'][^"'\s]{16,}'''
    # A bare token NAME is not a token. `oauth_token` on its own matched every
    # sentence that mentions the variable, which made the gate refuse prose and
    # taught people to reach for --no-verify. Require an assignment and a value.
    r'''|\b(oauth[_-]?token|refresh[_-]?token|access[_-]?token)\b\s*[:=]\s*\S{16,}''' r")",
    re.IGNORECASE)


def looks_secret(path):
    """The reason the file is refused, or None."""
    try:
        with open(path, "rb") as fh:
            blob = fh.read(262144)
    except OSError as e:
        return f"unreadable: {e}"
    if b"\0" in blob:
        return None  # binary. Not a config file, so not tracked either way.
    m = SECRET.search(blob.decode("utf-8", "replace"))
    return f"looks like a credential ({m.group(0)[:6]}...)" if m else None


def names(d, pattern):
    if not os.path.isdir(d):
        return set()
    import fnmatch
    return {f for f in os.listdir(d) if fnmatch.fnmatch(f, pattern)}


def walk(root, exclude):
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = [d for d in dirnames if d != ".git" and not any(
            fnmatch.fnmatch(os.path.normpath(os.path.join(rel_dir, d)), x) for x in exclude)]
        for f in filenames:
            rel = os.path.normpath(os.path.join(rel_dir, f))
            if any(fnmatch.fnmatch(rel, x) for x in exclude):
                continue
            out.add(rel)
    return out


def diff_one(e):
    """Returns (missing_in_repo, gone_from_live, changed) as lists of labels."""
    if e.get("tree"):
        ex = e.get("exclude", [])
        live = walk(e["live"], ex) if os.path.isdir(e["live"]) else set()
        repo = walk(e["repo_abs"], ex) if os.path.isdir(e["repo_abs"]) else set()
        changed = [f for f in sorted(live & repo)
                   if not filecmp.cmp(os.path.join(e["live"], f),
                                      os.path.join(e["repo_abs"], f), shallow=False)]
        return sorted(live - repo), sorted(repo - live), changed
    if "glob" in e:
        live, repo = names(e["live"], e["glob"]), names(e["repo_abs"], e["glob"])
        changed = [f for f in sorted(live & repo)
                   if not filecmp.cmp(os.path.join(e["live"], f),
                                      os.path.join(e["repo_abs"], f), shallow=False)]
        return sorted(live - repo), sorted(repo - live), changed
    # single file
    live_there, repo_there = os.path.exists(e["live"]), os.path.exists(e["repo_abs"])
    label = os.path.basename(e["live"])
    if live_there and not repo_there:
        return [label], [], []
    if repo_there and not live_there:
        return [], [label], []
    if live_there and repo_there and not filecmp.cmp(e["live"], e["repo_abs"], shallow=False):
        return [], [], [label]
    return [], [], []


REFUSED = []


def _copy(src, dst):
    """Copy unless the file looks like it holds a secret. LAW 21 outranks LAW 24."""
    why = looks_secret(src)
    if why:
        REFUSED.append((src, why))
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def pull_one(e):
    a, b, c = diff_one(e)
    if e.get("tree"):
        for f in a + c:
            _copy(os.path.join(e["live"], f), os.path.join(e["repo_abs"], f))
        for f in b:
            os.remove(os.path.join(e["repo_abs"], f))
        return len(a), len(b), len(c)
    if "glob" in e:
        os.makedirs(e["repo_abs"], exist_ok=True)
        for f in a + c:
            _copy(os.path.join(e["live"], f), os.path.join(e["repo_abs"], f))
        for f in b:
            os.remove(os.path.join(e["repo_abs"], f))
    else:
        if a or c:
            _copy(e["live"], e["repo_abs"])
        elif b:
            os.remove(e["repo_abs"])
    return len(a), len(b), len(c)


def restore_one(e, force):
    """Copy the committed copy back onto the machine. The reverse of pull_one.

    Refuses to overwrite a live file that differs unless --force. On a fresh
    machine nothing exists so nothing is refused; on a machine that already has
    an estate, silently overwriting is how a restore destroys the thing it was
    run to protect.
    """
    written, skipped = 0, []
    if e.get("tree") or "glob" in e:
        ex = e.get("exclude", [])
        repo = walk(e["repo_abs"], ex) if os.path.isdir(e["repo_abs"]) else set()
        if "glob" in e and not e.get("tree"):
            repo = names(e["repo_abs"], e["glob"])
        for f in sorted(repo):
            src, dst = os.path.join(e["repo_abs"], f), os.path.join(e["live"], f)
            if os.path.exists(dst) and not force:
                if not filecmp.cmp(src, dst, shallow=False):
                    skipped.append(f)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            written += 1
        return written, skipped
    if not os.path.exists(e["repo_abs"]):
        return 0, []
    if os.path.exists(e["live"]) and not force:
        if not filecmp.cmp(e["repo_abs"], e["live"], shallow=False):
            skipped.append(os.path.basename(e["live"]))
        return 0, skipped
    os.makedirs(os.path.dirname(e["live"]), exist_ok=True)
    shutil.copy2(e["repo_abs"], e["live"])
    return 1, []


BOARD = os.path.expanduser("~/.claude/ESTATE_BOARD.jsonl")


def board(kind, text):
    """Every session is handed the board at startup. LAW 28: an instrument
    nobody reads is not an instrument, and a log file is nobody."""
    try:
        import datetime
        with open(BOARD, "a") as fh:
            fh.write(json.dumps({
                "ts": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "from": "tracked.py", "kind": kind, "text": text}) + "\n")
    except OSError:
        pass


def sync():
    """Pull the drift, commit it, push it. Report only what a person would act on."""
    import subprocess
    paths = sorted({e["repo"].split("/")[0] for e in entries()})

    moved = 0
    for e in entries():
        moved += sum(pull_one(e))

    if REFUSED:
        board("secret-refused",
              "tracked.py refused to commit %d file(s) that look like credentials: %s. "
              "They belong in rebuild/PREREQUISITES.md by name, never by value."
              % (len(REFUSED), ", ".join(os.path.basename(p) for p, _ in REFUSED)))

    def git(*args):
        return subprocess.run(["git", "-C", HERE, *args],
                              capture_output=True, text=True, timeout=120)

    # -uall, because plain --porcelain collapses a new directory to one line and
    # the count then reports 1 where 8 files changed.
    status = git("status", "--porcelain", "-uall", "--", *paths).stdout
    if not status.strip():
        return 0

    changed = [l[3:] for l in status.splitlines()]
    git("add", "--", *paths)
    msg = ("LAW 24: %d load-bearing file(s) changed outside git\n\n%s\n\n"
           "Committed by the scheduled guard, not by a person.\n"
           % (len(changed), "\n".join("  " + c for c in changed)))
    c = git("commit", "-m", msg)
    if c.returncode:
        board("guard-broken", "tracked.py could not commit: " + c.stderr.strip()[:300])
        return 1
    p = git("push", "origin", "HEAD")
    if p.returncode:
        board("guard-broken",
              "tracked.py committed %d changed file(s) but could not push: %s. "
              "The record is local only until someone pushes it."
              % (len(changed), p.stderr.strip()[:200]))
        return 1
    board("tracked", "committed and pushed %d load-bearing file(s) changed outside git: %s"
          % (len(changed), ", ".join(changed[:8])))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--restore", action="store_true",
                    help="copy the committed files back onto the machine")
    ap.add_argument("--into", default=None,
                    help="treat DIR as the home directory. For the drill.")
    ap.add_argument("--force", action="store_true",
                    help="with --restore, overwrite live files that differ")
    a = ap.parse_args()

    if a.sync:
        return sync()

    if a.restore:
        total, blocked, generated = 0, [], []
        for e in entries(a.into):
            if e.get("generated"):
                generated.append((e["repo"], e["generated"]))
                continue
            n, skipped = restore_one(e, a.force)
            total += n
            blocked += [f"{e['repo']}/{f}" for f in skipped]
            if n:
                print(f"{e['repo']}: restored {n} file(s) to {e['live']}")
        print(f"\nrestored {total} file(s)"
              + (f" into {a.into}" if a.into else " onto this machine"))
        if blocked:
            print(f"{len(blocked)} live file(s) differ and were left alone. "
                  f"--force overwrites them:")
            for f in blocked[:20]:
                print(f"    {f}")
        for repo, how in generated:
            print(f"\n{repo}: NOT restored, it is generated. Run:  {how}")
            print("    These files have the home directory baked into them. Copying "
                  "them onto a\n    new machine installs jobs pointing at the old one.")
        print("\nWhat is NOT restored, because it was never committed: every "
              "credential.\nrebuild/PREREQUISITES.md lists each one by name and "
              "how a new machine gets it.")
        return 0

    drift = 0
    for e in entries():
        miss, gone, chg = diff_one(e)
        if a.pull:
            n = pull_one(e)
            if any(n):
                print(f"{e['repo']}: pulled {n[0]} new, {n[2]} changed, {n[1]} removed")
            continue
        if miss or gone or chg:
            drift += len(miss) + len(gone) + len(chg)
            print(f"{e['repo']}  ({e['why']})")
            for label, g in (("not committed", miss), ("gone from the machine", gone),
                             ("differs from the live file", chg)):
                for f in g:
                    print(f"    {label:26s} {f}")
        elif not a.check:
            print(f"{e['repo']}: in step")

    if a.pull:
        if REFUSED:
            print(f"\nREFUSED {len(REFUSED)} file(s). LAW 21: a secret is never committed.")
            for path, why in REFUSED:
                print(f"    {path}\n        {why}")
            print("    Record what these must contain in rebuild/PREREQUISITES.md, by name.")
        print("commit the result to record it")
        return 0
    if drift:
        print(f"\n{drift} difference(s). LAW 24: run `tracked.py --pull`, then commit.")
        return 1 if a.check else 0
    print(f"in step: every tracked path matches its committed copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
