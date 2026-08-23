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

A stale copy is worse than none, because it reads as a record. That is what
--check is for.
"""
import argparse, filecmp, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "tracked.json")


def entries():
    for e in json.load(open(MANIFEST)):
        e["live"] = os.path.expanduser(e["live"])
        e["repo_abs"] = os.path.join(HERE, e["repo"])
        yield e


def names(d, pattern):
    if not os.path.isdir(d):
        return set()
    import fnmatch
    return {f for f in os.listdir(d) if fnmatch.fnmatch(f, pattern)}


def diff_one(e):
    """Returns (missing_in_repo, gone_from_live, changed) as lists of labels."""
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


def pull_one(e):
    a, b, c = diff_one(e)
    if "glob" in e:
        os.makedirs(e["repo_abs"], exist_ok=True)
        for f in a + c:
            shutil.copy2(os.path.join(e["live"], f), os.path.join(e["repo_abs"], f))
        for f in b:
            os.remove(os.path.join(e["repo_abs"], f))
    else:
        os.makedirs(os.path.dirname(e["repo_abs"]), exist_ok=True)
        if a or c:
            shutil.copy2(e["live"], e["repo_abs"])
        elif b:
            os.remove(e["repo_abs"])
    return len(a), len(b), len(c)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--pull", action="store_true")
    a = ap.parse_args()

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
        print("commit the result to record it")
        return 0
    if drift:
        print(f"\n{drift} difference(s). LAW 24: run `tracked.py --pull`, then commit.")
        return 1 if a.check else 0
    print(f"in step: every tracked path matches its committed copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
