#!/usr/bin/env python3
"""Everything load-bearing is in git, or this exits 1 (LAW 24).

Five classes, because answering the question for one of them and calling it
closed is how the last four holes survived:

  runners   every program a launchd job executes
  declared  the laws, settings, agent definitions, skills, job definitions
  repos     every estate repo clean and pushed, not just committed locally
  mirrors   the live copy and the committed copy still identical
  secrets   a credential file has a committed example naming its keys, and the
            values are still absent from the repo (LAW 21 outranks LAW 24)

What it is NOT allowed to do is pass because it did not look. Every class that
cannot run reports UNKNOWN and fails the sweep, never a quiet zero.
"""
import glob, json, os, plistlib, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from estate.ingit import covered, mirrors, HOME, REPO   # noqa: E402

DECL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "load-bearing.json")
FOREIGN = ("com.apple", "com.valvesoftware", "com.adobe", "com.docker",
           "com.cisco", "com.ollama", "com.openssh", "com.google", "com.microsoft")


def _generated(d):
    """Live paths are written with a ~ in the manifest; covered() compares absolutes."""
    return {os.path.expanduser(k): v for k, v in d.get("generated", {}).items()}


def _skipped(name, rules):
    """A vendor's job, or a definition somebody deliberately parked, is not ours."""
    return (name.startswith(tuple(rules.get("prefixes", [])))
            or name.endswith(tuple(rules.get("suffixes", [])))
            or any(c in name for c in rules.get("contains", [])))


def sh(args, cwd=None, t=60):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=t, cwd=cwd)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 127, "", f"{type(e).__name__}: {e}"


def _is_system(p):
    return (p.startswith(("/usr/", "/bin/", "/sbin/", "/System/", "/opt/homebrew/"))
            or os.path.basename(p) in ("python3", "python", "node", "bash", "sh",
                                       "zsh", "env", "caffeinate"))


def _programs(argv):
    """Program arguments naming a file, minus interpreters and minus flag values.
    `--out /x/y.json` is where a job WRITES, not what it runs."""
    out, skip = [], False
    for i, a in enumerate(argv):
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            if "=" not in a and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                skip = True
            continue
        if a.startswith("/") and not _is_system(a):
            out.append(a)
    return out


def check_runners(d, mm):
    holes, ok, gen = [], 0, _generated(d)
    for f in sorted(glob.glob(os.path.join(HOME, "Library/LaunchAgents/*.plist"))):
        label = os.path.basename(f)[:-6]
        if _skipped(os.path.basename(f), d.get("skip_names", {})):
            continue
        try:
            argv = plistlib.load(open(f, "rb")).get("ProgramArguments", [])
        except Exception as e:
            holes.append(f"{label}: unreadable plist: {e}")
            continue
        for a in _programs(argv):
            if not os.path.exists(a):
                holes.append(f"{label}: target missing: {a}")
            elif covered(a, mm, gen) is None:
                holes.append(f"{label}: not in git: {a}")
            else:
                ok += 1
    return ok, holes


def check_declared(d, mm):
    holes, ok, gen = [], 0, _generated(d)
    skip = d.get("skip_names", {})
    for e in d["paths"]:
        p = os.path.expanduser(e["path"])
        if not os.path.exists(p):
            holes.append(f"{e['path']}: missing ({e['why']})")
            continue
        if os.path.isdir(p):
            # A directory is kept only if its files are. One uncovered file is a hole.
            files = [os.path.join(r, n) for r, _, ns in os.walk(p) for n in ns
                     if not n.startswith(".") and not _skipped(n, skip)]
            bad = [f for f in files if covered(f, mm, gen) is None]
            if bad:
                holes.append(f"{e['path']}: {len(bad)} of {len(files)} not in git "
                             f"(first: {os.path.relpath(bad[0], HOME)})")
            else:
                ok += 1
        elif covered(p, mm, gen) is None:
            holes.append(f"{e['path']}: not in git ({e['why']})")
        else:
            ok += 1
    return ok, holes


def check_repos(d, _mm):
    holes, ok = [], 0
    for e in d["repos"]:
        p = os.path.expanduser(e["path"])
        if not os.path.isdir(os.path.join(p, ".git")):
            holes.append(f"{e['path']}: not a git repo")
            continue
        dirty = sh(["git", "-C", p, "status", "--porcelain"])[1].splitlines()
        # Untracked files are somebody's work in flight. Modified TRACKED files are
        # an edit to something the estate already depends on, which is the hole.
        noisy = tuple(d.get("always_dirty", {}).get("paths", []))
        mod = [l for l in dirty if not l.startswith("??")
               and not l[3:].strip().startswith(noisy)]
        sh(["git", "-C", p, "fetch", "-q", "origin"], t=90)
        rc, ab, _ = sh(["git", "-C", p, "rev-list", "--left-right", "--count", "HEAD...@{u}"])
        ahead = ab.split()[0] if rc == 0 and ab else "?"
        if mod:
            holes.append(f"{e['path']}: {len(mod)} tracked file(s) edited and not committed")
        if rc != 0:
            holes.append(f"{e['path']}: branch has no upstream, nothing off this machine holds it")
        elif ahead not in ("0", "?"):
            holes.append(f"{e['path']}: {ahead} commit(s) never pushed")
        if not mod and rc == 0 and ahead == "0":
            ok += 1
    return ok, holes


def check_mirrors(_d, _mm):
    rc, out, err = sh([sys.executable, os.path.join(REPO, "tracked.py"), "--check"], t=180)
    if rc == 0:
        return 1, []
    bad = [l.strip() for l in out.splitlines()
           if l.strip().startswith(("not committed", "differs", "missing"))]
    return 0, bad or [(out or err).strip().splitlines()[-1][:160] or f"tracked.py exit {rc}"]


def check_secrets(d, mm):
    """The names are kept so the estate can be rebuilt. The values never are."""
    holes, ok = [], 0
    for e in d["secrets"]:
        p = os.path.expanduser(e["path"])
        ex = os.path.join(REPO, e["example"])
        if not os.path.exists(p):
            holes.append(f"{e['path']}: missing ({e['why']})")
            continue
        if not os.path.exists(ex):
            holes.append(f"{e['path']}: no committed example at {e['example']}")
            continue
        if covered(ex, mm) is None:
            holes.append(f"{e['example']}: the example itself is not in git")
            continue
        live_keys = {l.split("=")[0].strip().lstrip("export ").strip()
                     for l in open(p) if "=" in l and not l.strip().startswith("#")}
        ex_keys = {l.split("=")[0].strip().lstrip("export ").strip()
                   for l in open(ex) if "=" in l and not l.strip().startswith("#")}
        missing = live_keys - ex_keys
        if missing:
            holes.append(f"{e['example']}: does not name {len(missing)} key(s) the live file sets")
            continue
        # And the values must still be absent. A leaked example is worse than none.
        leaked = [k for k in ex_keys
                  if len(next((l.split("=", 1)[1].strip().strip('"\'')
                               for l in open(ex) if l.split("=")[0].strip().endswith(k)), "")) > 8]
        if leaked:
            holes.append(f"{e['example']}: {len(leaked)} key(s) carry a value, LAW 21")
            continue
        ok += 1
    return ok, holes


CLASSES = [("runners", check_runners), ("declared", check_declared),
           ("repos", check_repos), ("mirrors", check_mirrors),
           ("secrets", check_secrets)]


def main():
    quiet = "--quiet" in sys.argv
    d = json.load(open(DECL))
    mm = mirrors()
    total_holes, lines = 0, []
    for name, fn in CLASSES:
        try:
            ok, holes = fn(d, mm)
        except Exception as e:
            ok, holes = 0, [f"the {name} check could not run: {type(e).__name__}: {e}"]
        total_holes += len(holes)
        lines.append("  %-9s kept=%-3d holes=%d" % (name, ok, len(holes)))
        for h in holes:
            lines.append("     HOLE  " + h)
    if not quiet or total_holes:
        print("\n".join(lines))
    print("load-bearing holes: %d" % total_holes)
    return 1 if total_holes else 0


if __name__ == "__main__":
    sys.exit(main())
