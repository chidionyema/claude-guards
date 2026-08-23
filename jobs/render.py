#!/usr/bin/env python3
"""Declare a scheduled job once. Generate the platform's file from it.

LAW 19: portability outranks detection. A job used to BE a launchd plist with
this machine's home directory typed into it 174 times. Declared here instead,
with {HOME} as a placeholder, so the same declaration renders on any account and
a second renderer for another platform is a small job rather than a rewrite.

    render.py --check              does the live directory match the manifest?
    render.py --write              generate plists into ~/Library/LaunchAgents
    render.py --write --into DIR   generate somewhere harmless first
    render.py --platform systemd   what is not built yet, named honestly

launchctl runs the definition it loaded at bootstrap, not the file on disk, so
writing a plist changes nothing until the job is booted out and back in.
"""
import argparse, json, os, plistlib, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "jobs.json")
PLATFORMS = os.path.join(HERE, "platforms.json")
LIVE = os.path.expanduser("~/Library/LaunchAgents")


def fill(v, home):
    if isinstance(v, str):  return v.replace("{HOME}", home)
    if isinstance(v, list): return [fill(x, home) for x in v]
    if isinstance(v, dict): return {k: fill(x, home) for k, x in v.items()}
    return v


def resolve(job, plat):
    """Turn a platform-neutral declaration back into one platform's strings.

    Two things in a job are not portable and are declared without a platform in
    them. The program is a placeholder such as {PYTHON3_SYSTEM}, because
    /usr/bin/python3 does not exist off macOS. A search path is a LIST of
    directories, because ':' is not a separator everywhere. This function is
    where a platform's own names enter, and jobs/platforms.json is the only
    file that holds them."""
    t = json.load(open(PLATFORMS))[plat]
    progs, sep = t["programs"], t["path_separator"]

    def prog(a):
        # {HOME}/x is not a program placeholder; only a whole-value one is.
        return progs.get(a[1:-1], a) if a.startswith("{") and a.endswith("}") else a

    d = dict(job)
    if d.get("ProgramArguments"):
        d["ProgramArguments"] = [prog(a) for a in d["ProgramArguments"]]
    if "Program" in d:
        d["Program"] = prog(d["Program"])
    env = d.get("EnvironmentVariables")
    if env:
        d["EnvironmentVariables"] = {
            k: (sep.join(v) if isinstance(v, list) else v) for k, v in env.items()}
    return d


def render(job, home):
    job = resolve(job, "launchd")
    d = {k: fill(v, home) for k, v in job.items() if k != "label"}
    d["Label"] = job["label"]
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--into", default=LIVE)
    ap.add_argument("--platform", default="launchd")
    ap.add_argument("--home", default=os.path.expanduser("~"))
    a = ap.parse_args()

    if a.platform == "windows":
        # Delegated rather than reimplemented: Task Scheduler XML shares no keys
        # with a plist, so one renderer per platform is the cost of being able to
        # leave (LAW 19), not duplication.
        import subprocess
        return subprocess.run(
            [sys.executable, os.path.join(HERE, "render_windows.py")]
            + (["--write", "--into", a.into] if a.write else ["--check"])).returncode

    if a.platform != "launchd":
        print(f"no renderer for {a.platform} yet. The manifest is platform-neutral;")
        print(f"only this renderer is macOS. Write jobs/render_{a.platform}.py to add one.")
        return 2

    jobs = json.load(open(MANIFEST))

    if a.write:
        os.makedirs(a.into, exist_ok=True)
        written, kept = 0, 0
        for label, job in sorted(jobs.items()):
            p = os.path.join(a.into, label + ".plist")
            want = render(job, a.home)
            # Only rewrite a plist whose CONTENT differs. plistlib drops XML
            # comments, and 12 of these carry a note saying why the job is
            # shaped the way it is. Rewriting a file that already says the right
            # thing destroyed 9 of those notes once; skipping the no-op write
            # is what stops it happening again.
            if os.path.exists(p):
                try:
                    if plistlib.load(open(p, "rb")) == want:
                        kept += 1
                        continue
                except Exception:
                    pass
            with open(p, "wb") as fh:
                plistlib.dump(want, fh)
            written += 1
        print(f"{written} plists written into {a.into} for home={a.home}, "
              f"{kept} already correct and left alone with their comments")
        if a.into == LIVE:
            print("launchd still runs the OLD definitions. bootout and bootstrap each job.")
        return 0

    # --check: compare the manifest's output against what is on disk
    differ, missing = [], []
    for label, job in sorted(jobs.items()):
        p = os.path.join(LIVE, label + ".plist")
        if not os.path.exists(p):
            missing.append(label); continue
        if plistlib.load(open(p, "rb")) != render(job, a.home):
            differ.append(label)
    extra = sorted({f[:-6] for f in os.listdir(LIVE) if f.endswith(".plist")} - set(jobs)
                   ) if os.path.isdir(LIVE) else []

    for name, group in (("declared but not installed", missing),
                        ("installed but differs from the manifest", differ)):
        if group:
            print(f"{name}: {len(group)}")
            for l in group: print(f"    {l}")
    if extra:
        print(f"installed but not declared (vendor jobs are expected here): {len(extra)}")
        for l in extra: print(f"    {l}")

    if not (missing or differ):
        print(f"in step: {len(jobs)} declared jobs match the installed plists")
        return 0
    return 1 if a.check else 0


if __name__ == "__main__":
    sys.exit(main())
