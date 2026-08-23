#!/usr/bin/env python3
"""Assert every scheduled job on this Mac can still recover itself.

The founder's standard, 2026-08-23: "bsiclly if i disappered today the esate
should be able to run itself". That is a claim about recovery, and recovery is
the one property nothing here was measuring. Every other instrument on this
machine grades output -- was the file fresh, did the command exit 0 -- and all
of those are downstream of a job actually getting a turn.

Six ways a job stops recovering itself, each found at least once on this estate:

1. Its program is not on disk. launchd reports the job, the job runs, the shell
   cannot find the file and exits. See launchctl-runs-the-loaded-definition: a
   moved script leaves the job reporting exit 0 while doing nothing.
2. It has no recovery path at all -- no KeepAlive, no RunAtLoad, no interval.
   It ran once when it was loaded and will never run again.
3. It is a live service with no KeepAlive, so the first crash is permanent and
   nothing restarts it until the next reboot.
4. It is behind estate-gate and has never once completed a run. Found tonight:
   com.founder.agentcert and com.prospector.launchd-held fire on the same second
   every hour, lost the slot race every time, and had never run.
5. It is loaded in launchd with no plist on disk, so it dies at the next reboot
   and nothing brings it back.
6. Its plist is on disk and it is not loaded, so it is already not running and
   nothing will notice.

A job deliberately parked is not a defect, but it has to say so out loud, which
is what RETIRED is for. Anything else is graded.
"""
import calendar
import os
import plistlib
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".estate", "state")

PLIST_DIRS = [
    os.path.join(HOME, "Library", "LaunchAgents"),
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
]

#: The estate's own jobs. Apple's and third-party jobs are not ours to grade.
OURS = ("com.prospector", "com.estate", "com.founder", "com.chidionyema", "ai.")

#: Jobs that are meant to be unloaded, with the reason. An entry here is a
#: decision somebody made and can be argued with; a job missing from launchd
#: with no entry here is an accident nobody noticed.
RETIRED = {
    "ai.hermes.gateway": "REQ-116: the old estate held the Telegram poll and made "
                         "The Architect deaf for 31.5 hours. One token, one poller.",
    "com.chidionyema.graphify-sweep": "2026-08-24: it swept ~/Documents/code every "
        "30 minutes, took 2m41s to 6m52s of CPU per run on a 12-core machine that "
        "was already at load 128, and exited 1 on every completed run in gate.log. "
        "Nothing consumed its output: graphify_session_hook.py is registered in no "
        "hooks block, so settings.json holds a Read permission for graphify-out/** "
        "and nothing that writes it. A job with no reader is not an instrument "
        "(LAW 28). The plist stays on disk with its paths corrected; to bring it "
        "back, register the session hook first, then bootstrap it.",
}

#: A gated job is graded stale after this many of its own intervals.
STALE_TURNS = 3


def launchctl_list():
    """label -> (pid, last exit code), for everything launchd currently knows."""
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    live = {}
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3:
            live[parts[2]] = (parts[0].strip(), parts[1].strip())
    return live


def plists():
    """label -> (path, parsed) for every job definition on disk."""
    found = {}
    for d in PLIST_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".plist"):
                continue
            path = os.path.join(d, name)
            try:
                with open(path, "rb") as fh:
                    parsed = plistlib.load(fh)
            except Exception as exc:
                found[name[:-6]] = (path, {"__unreadable__": str(exc)})
                continue
            found[parsed.get("Label", name[:-6])] = (path, parsed)
    return found


def program_paths(pl):
    """Every path this job needs in order to do anything."""
    args = pl.get("ProgramArguments") or []
    prog = pl.get("Program") or (args[0] if args else "")
    #: A gated job's real work is the first path AFTER the gate and the label,
    #: so both are checked: a present gate wrapping a deleted script is the
    #: silent no-op this drill exists to catch.
    paths = {prog}
    for a in args[1:]:
        if a.startswith("/"):
            paths.add(a)
            break
    return sorted(p for p in paths if p)


def age_seconds(path):
    try:
        return time.time() - os.stat(path).st_mtime
    except OSError:
        return None


def grade(label, pl, live):
    """Every reason this job cannot recover itself. Empty list means it can."""
    if "__unreadable__" in pl:
        return [f"its plist will not parse: {pl['__unreadable__']}"]

    faults = []
    pid, _exit = live.get(label, ("-", "-"))
    alive = pid not in ("-", "")
    keepalive = bool(pl.get("KeepAlive"))
    runatload = bool(pl.get("RunAtLoad"))
    interval = pl.get("StartInterval")
    calendar = bool(pl.get("StartCalendarInterval"))
    gated = "estate-gate" in " ".join(pl.get("ProgramArguments") or [])

    for path in program_paths(pl):
        if not os.path.exists(path):
            faults.append(f"its program is not on disk: {path}")

    if not (keepalive or runatload or interval or calendar):
        faults.append("it has no recovery path at all: it ran once when it was "
                      "loaded and nothing will ever run it again")

    if alive and not keepalive and not interval and not calendar:
        faults.append(f"it is running as pid {pid} with no KeepAlive, so the "
                      f"first crash is permanent until a reboot")

    if gated and interval:
        faults.extend(grade_gated(label, interval))

    return faults


def gate_running_now(label):
    """True when a gate process for this label is alive at this moment.

    A job that has not finished a run because it is in the middle of one is not
    a defect. The first version of this drill missed that and called
    com.estate.bundlepush starved while it was pushing a bundle every seven
    seconds. Absence of a finish is not evidence of a failure to start.
    """
    out = subprocess.run(["pgrep", "-f", f"estate-gate {label} "],
                         capture_output=True, text=True).stdout
    return bool(out.strip())


def last_gate_verdict(label):
    """The last thing the gate said about this job: (verb, age in seconds)."""
    log = os.path.join(STATE, "gate.log")
    try:
        with open(log, encoding="utf-8", errors="replace") as fh:
            lines = [l for l in fh if f" {label} " in l]
    except OSError:
        return None, None
    if not lines:
        return None, None
    parts = lines[-1].split()
    stamp, verb = parts[0], parts[2]
    try:
        #: The gate stamps UTC. timegm reads it as UTC; mktime would read it as
        #: local and be an hour out, which is exactly the mistake that made
        #: tonight's missing log line look like a missing log line.
        when = calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return verb, None
    return verb, time.time() - when


def grade_gated(label, interval):
    """Why a gated job is not getting its work done, told apart by cause.

    Three failures wear the same symptom -- no gate.lastrun -- and each needs a
    different repair, so LAW 29 says name the step rather than the symptom:
    losing every slot race is a gate problem, dying mid-run is a job problem,
    and running right now is not a problem at all.
    """
    lastrun = os.path.join(STATE, f"gate.lastrun.{label}")
    age = age_seconds(lastrun)
    verb, verb_age = last_gate_verdict(label)

    if gate_running_now(label):
        return []

    if age is None:
        if verb is None:
            return []          #: the gate has never seen it: newly installed
        if verb == "RUN":
            return [f"the gate started it {verb_age / 60:.0f} minutes ago, no "
                    f"process is left, and it never reported finishing: it is "
                    f"dying mid-run"]
        return ["it has never once completed a run: it loses its turn every time"]

    if age > interval * STALE_TURNS:
        return [f"its last completed run was {age / 3600:.1f}h ago and it is "
                f"meant to run every {interval / 3600:.1f}h"]
    return []


def main():
    live = launchctl_list()
    on_disk = plists()
    ours = {k: v for k, v in on_disk.items() if k.startswith(OURS)}
    ours_live = {k for k in live if k.startswith(OURS)}

    findings = []

    for label, (path, pl) in sorted(ours.items()):
        if label not in live:
            why = RETIRED.get(label)
            if why:
                continue
            findings.append((label, ["its plist is on disk and it is not loaded, "
                                     "so it is not running and nothing will notice"]))
            continue
        faults = grade(label, pl, live)
        if faults:
            findings.append((label, faults))

    for label in sorted(ours_live - set(ours)):
        findings.append((label, ["it is loaded with no plist on disk, so it dies "
                                 "at the next reboot and nothing brings it back"]))

    parked = sum(1 for label in RETIRED if label not in live)
    graded = len(ours) + len(ours_live - set(ours)) - parked
    print(f"{len(ours)} job definitions on disk, {len(ours_live)} loaded, "
          f"{parked} deliberately retired, {graded - len(findings)} of {graded} "
          f"can recover themselves")
    for label, why in RETIRED.items():
        if label not in live:
            print(f"RETIRED {label}: {why}")
    print()

    for label, faults in findings:
        print(f"CANNOT RECOVER  {label}")
        for f in faults:
            print(f"                {f}")

    if findings:
        print()
        print(f"DRILL FAILED: {len(findings)} jobs cannot recover themselves.")
        return 1
    print("DRILL PASSED: every job on this Mac restarts, reschedules or is "
          "explicitly retired, and every one of them has run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
