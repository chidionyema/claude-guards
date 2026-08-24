#!/usr/bin/env python3
"""Put a loaded launchd job under Healthchecks dead-man monitoring, or say why it must not be.

REPORT MODE IS THE DEFAULT. `--fix` is the only thing that writes.

WHY THIS IS NOT A HAND EDIT. 34 of 46 loaded jobs are unwrapped, measured by
`measure-wrap-coverage.sh`. Editing 34 plists by hand is 34 chances to typo a path into a job
that then reports exit 0 while doing nothing -- which is the exact incident behind
"exit 0 is not proof of work". This does one mechanical transform and prints every one it
refuses.

WHY IT IS NOT A PERMANENT INSTRUMENT. It is a migration. When every job is wrapped it has no
work left, and the thing that keeps the estate honest afterwards is
`measure-wrap-coverage.sh`, which counts coverage from `launchctl list` rather than from this
script's own opinion of what it did.

THE TRANSFORM. ProgramArguments gains two entries at the front:

    ["/usr/bin/python3", "tick.py"]
      -> ["<hc-wrap.sh>", "<slug>", "/usr/bin/python3", "tick.py"]

hc-wrap.sh pings <slug>/start, runs the job unchanged, and pings <slug>/<exit code>. It never
changes the job's exit status and it never fails the job when the receiver is down.

WHAT IT REFUSES, AND WHY EACH REFUSAL IS NOT A GAP.

  already wrapped     nothing to do.
  no schedule         a dead-man check asks "did this run when it should have?". A job with no
                      StartInterval, StartCalendarInterval or WatchPaths has no "should have",
                      so a check for it would sit in "new" forever and teach people to ignore
                      the board.
  always-on           KeepAlive means the process is meant never to exit. hc-wrap pings on
                      exit, so wrapping one produces a check that only ever fires when the
                      service dies and is silent while it is broken-but-running. Those need a
                      liveness ping from inside the process, which is different work.
  Program, not        launchd's `Program` key takes a single executable with no arguments.
  ProgramArguments    Prepending a wrapper means switching the job to ProgramArguments, which
                      changes more than monitoring. Refused rather than done silently.
  vendor              com.apple.*, homebrew.*, com.valvesoftware.* and the like. Not ours.

Usage:
    wrap-jobs.py                      # report every loaded job and what would happen
    wrap-jobs.py --fix LABEL [LABEL]  # wrap exactly the labels named, then reload them
"""
from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
LAUNCH_AGENTS = HOME / "Library" / "LaunchAgents"
HC_WRAP = HOME / ".claude" / "scripts" / "hc-wrap.sh"

# Vendor prefixes. Same list as measure-wrap-coverage.sh; they are not the estate's jobs and
# editing them would be editing someone else's software.
VENDOR = ("com.apple.", "application.", "0x", "com.valvesoftware.", "homebrew.")

SCHEDULE_KEYS = ("StartInterval", "StartCalendarInterval", "WatchPaths", "QueueDirectories")


def loaded_labels() -> list[str]:
    """The jobs launchd is actually running, not the plists on disk.

    These differ: a plist can sit unloaded, and a loaded job can point at a plist that has since
    been edited. `launchctl list` is the live answer, which is why coverage is counted from it.
    """
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    labels = []
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        label = parts[2].strip()
        if label and not label.startswith(VENDOR):
            labels.append(label)
    return labels


def slug_for(label: str) -> str:
    """`com.prospector.offsite-backup` -> `prospector-offsite-backup`.

    The whole label minus its leading domain, not just the last component: `backup` alone would
    not say whose backup it is, and the existing 12 checks are already inconsistent enough
    (`estate-restic` for `com.estate.restic-backup`, `watch` for `ai.aiden.watch`) that a reader
    cannot map a board row back to a job without guessing.
    """
    parts = label.split(".")
    if len(parts) > 1 and parts[0] in ("com", "ai", "org", "net", "io"):
        parts = parts[1:]
    return "-".join(parts)


def classify(label: str) -> tuple[str, str, dict | None, Path | None]:
    """Return (verdict, reason, plist contents, plist path)."""
    path = LAUNCH_AGENTS / f"{label}.plist"
    if not path.is_file():
        return "no-plist", f"no plist at {path}", None, None
    try:
        data = plistlib.loads(path.read_bytes())
    except Exception as e:  # a plist this cannot parse is one it must not rewrite
        return "unreadable", f"{type(e).__name__}: {e}", None, path

    argv = data.get("ProgramArguments")
    if argv is None:
        if "Program" in data:
            return "program-key", "uses Program, not ProgramArguments", data, path
        return "no-command", "neither Program nor ProgramArguments", data, path
    if any(str(HC_WRAP.name) in str(a) for a in argv):
        return "wrapped", f"already pings as {argv[1] if len(argv) > 1 else '?'}", data, path
    if data.get("KeepAlive"):
        return "always-on", "KeepAlive: meant never to exit, so an exit ping says nothing", data, path
    if not any(k in data for k in SCHEDULE_KEYS):
        return "no-schedule", "no StartInterval/StartCalendarInterval/WatchPaths", data, path
    return "wrappable", f"-> {slug_for(label)}", data, path


def wrap(label: str, data: dict, path: Path) -> None:
    """Rewrite the plist, then make launchd read it.

    The reload is not optional. launchctl runs the definition it loaded, not the file on disk:
    an edited plist with no bootout/bootstrap leaves the job running the old command while the
    file says otherwise, which is a lie that survives every check that reads the file.
    """
    backup = path.with_suffix(".plist.bak")
    shutil.copy2(path, backup)
    data["ProgramArguments"] = [str(HC_WRAP), slug_for(label)] + list(data["ProgramArguments"])
    path.write_bytes(plistlib.dumps(data))

    check = subprocess.run(["plutil", "-lint", str(path)], capture_output=True, text=True)
    if check.returncode != 0:
        shutil.copy2(backup, path)
        raise SystemExit(f"{label}: plutil -lint refused the rewritten plist, restored the backup.\n{check.stdout}{check.stderr}")

    uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True, text=True)
    boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)],
                          capture_output=True, text=True)
    if boot.returncode != 0:
        raise SystemExit(f"{label}: bootstrap failed rc={boot.returncode}\n{boot.stdout}{boot.stderr}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", nargs="+", metavar="LABEL",
                    help="wrap exactly these labels; without it nothing is written")
    args = ap.parse_args(argv[1:])

    if not HC_WRAP.is_file():
        print(f"FAIL: {HC_WRAP} does not exist. Wrapping a job in a missing script would stop it.",
              file=sys.stderr)
        return 1

    labels = loaded_labels()
    if not labels:
        print("FAIL: launchctl list returned no estate jobs. Refusing rather than reporting "
              "'nothing to do', which is what an empty list looks like.", file=sys.stderr)
        return 1

    verdicts: dict[str, list[str]] = {}
    detail: dict[str, tuple[str, dict | None, Path | None]] = {}
    for label in sorted(labels):
        verdict, reason, data, path = classify(label)
        verdicts.setdefault(verdict, []).append(label)
        detail[label] = (reason, data, path)

    if not args.fix:
        for verdict in ("wrappable", "wrapped", "always-on", "no-schedule", "program-key",
                        "no-command", "unreadable", "no-plist"):
            group = verdicts.get(verdict, [])
            if not group:
                continue
            print(f"\n== {verdict} ({len(group)}) ==")
            for label in group:
                print(f"  {label:<38} {detail[label][0]}")
        n = len(verdicts.get("wrappable", []))
        print(f"\ntotal={len(labels)}  wrapped={len(verdicts.get('wrapped', []))}  "
              f"wrappable={n}  refused={len(labels) - n - len(verdicts.get('wrapped', []))}")
        print("\nNothing was written. Pass --fix LABEL [LABEL ...] to wrap named jobs.")
        return 0

    rc = 0
    for label in args.fix:
        verdict, reason, data, path = classify(label)
        if verdict != "wrappable":
            print(f"REFUSED {label}: {verdict} -- {reason}")
            rc = 1
            continue
        wrap(label, data, path)
        print(f"WRAPPED {label} as {slug_for(label)}; reloaded")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
