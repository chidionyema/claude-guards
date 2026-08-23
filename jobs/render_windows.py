#!/usr/bin/env python3
"""Render the job manifest as Windows Task Scheduler XML, and say what is lost.

LAW 19: portability outranks detection. jobs.json declares 28 scheduled jobs in
launchd's vocabulary. This turns each one into a Task Scheduler task and, more
importantly, refuses to pretend the translation is complete when it is not.

    render_windows.py --check          translate in memory, print the report
    render_windows.py --write --into D write one .xml per job into D

Exit 0 only when every job survives the crossing. Exit 1 when any job loses a
guarantee, with the job and the key named. A renderer that silently drops
KeepAlive produces 28 files and a scheduler that does not do what the manifest
says, which is worse than no renderer at all (LAW 28).

Import into Windows with:
    schtasks /Create /TN "<label>" /XML <label>.xml

Nothing here runs on macOS beyond generating text, and nothing here needs a
Windows machine to be tested. That is the point: the gap is measurable today.
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "jobs.json")
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"

# Keys this renderer honours. Anything in the manifest and not in here is
# reported against the job that uses it, every run.
HANDLED = {
    "label", "Program", "ProgramArguments", "WorkingDirectory",
    "StartInterval", "StartCalendarInterval", "RunAtLoad", "KeepAlive",
    "StandardOutPath", "StandardErrorPath", "EnvironmentVariables",
}

# Keys with no Task Scheduler equivalent at all. Named so the report says what
# was lost rather than how many things were lost.
NO_EQUIVALENT = {
    "WatchPaths": "Task Scheduler has no file-watch trigger. This job fires on a "
                  "path changing and cannot on Windows without a helper process.",
    "ThrottleInterval": "no minimum respawn gap; RestartInterval is the nearest "
                        "and applies only after a failure.",
    "Nice": "no process nice level.",
    "LowPriorityIO": "no per-task IO priority.",
    "ProcessType": "no scheduler class hint.",
    "SoftResourceLimits": "no per-task rlimits.",
    "ExitTimeOut": "no configurable SIGTERM-to-SIGKILL gap.",
    "LimitLoadToSessionType": "no Aqua/Background session distinction.",
    "SteamContentPaths": "not a launchd key either; carried by mistake.",
}


def win_path(s):
    """{HOME} is %USERPROFILE% and POSIX separators are backslashes."""
    return s.replace("{HOME}", "%USERPROFILE%").replace("/", "\\")


def posix_only(cmd):
    """Does this command name a path that cannot exist on Windows?"""
    return cmd.startswith("/") or cmd.startswith("\\usr\\") or cmd.startswith("\\bin\\")


def build_command(job):
    """(command, arguments, losses, translations).

    Env vars and log redirection have no native Task Scheduler home, so they go
    through one cmd.exe wrapper rather than being dropped. That is a translation
    and it is stated, but it is NOT a loss -- counting it as one put all 28 jobs
    in the lossy column and made the headline number say nothing (LAW 28)."""
    argv = job.get("ProgramArguments") or ([job["Program"]] if "Program" in job else [])
    if not argv:
        return None, None, ["no Program or ProgramArguments; nothing to run"], []
    argv = [win_path(a) for a in argv]

    # The check is on the program the job actually names. Running it after the
    # cmd.exe wrapper is chosen tests the wrapper, which is always portable, and
    # the whole class of unrunnable POSIX interpreters then reports clean.
    losses = []
    if posix_only(argv[0]):
        losses.append(f"the program is a POSIX path ({argv[0]}); no such file exists "
                      f"on Windows, so this task is generated but cannot run until "
                      f"the interpreter is named portably")

    env = job.get("EnvironmentVariables") or {}
    out, err = job.get("StandardOutPath"), job.get("StandardErrorPath")
    trans = []

    # A POSIX PATH is colon-separated. Turning its slashes round produces a
    # string Windows accepts and then silently ignores every entry of, which is
    # worse than an error. Name it rather than emit a confidently wrong PATH.
    for k, v in sorted(env.items()):
        if isinstance(v, str) and v.count(":") >= 2 and "/" in v:
            losses.append(f"{k} is a colon-separated POSIX search path with "
                          f"{v.count(':') + 1} entries; Windows separates on ';' "
                          f"and none of these directories exist there")

    if not env and not out and not err:
        return argv[0], " ".join(argv[1:]), losses, trans

    parts = [f'set "{k}={win_path(v)}"&& ' for k, v in sorted(env.items())]
    inner = " ".join(f'"{a}"' if " " in a else a for a in argv)
    if out:
        inner += f' >>"{win_path(out)}"'
    if err:
        inner += f' 2>>"{win_path(err)}"' if err != out else " 2>&1"
    trans.append("environment and log redirection go through a cmd.exe wrapper; "
                 "Task Scheduler has neither natively")
    return "cmd.exe", '/c "' + "".join(parts) + inner + '"', losses, trans


def triggers(job, root_triggers):
    """Returns notes about anything the trigger translation could not carry."""
    notes = []
    if job.get("RunAtLoad"):
        ET.SubElement(root_triggers, "LogonTrigger").append(_enabled())

    interval = job.get("StartInterval")
    if interval:
        t = ET.SubElement(root_triggers, "TimeTrigger")
        ET.SubElement(t, "StartBoundary").text = "2026-01-01T00:00:00"
        ET.SubElement(t, "Enabled").text = "true"
        rep = ET.SubElement(t, "Repetition")
        if interval < 60:
            notes.append(f"StartInterval is {interval}s; Task Scheduler's floor is "
                         f"60s, so this job runs less often on Windows")
            interval = 60
        ET.SubElement(rep, "Interval").text = f"PT{int(interval)}S"
        ET.SubElement(rep, "StopAtDurationEnd").text = "false"

    cal = job.get("StartCalendarInterval")
    if cal:
        for entry in (cal if isinstance(cal, list) else [cal]):
            t = ET.SubElement(root_triggers, "CalendarTrigger")
            hour, minute = entry.get("Hour", 0), entry.get("Minute", 0)
            ET.SubElement(t, "StartBoundary").text = f"2026-01-01T{hour:02d}:{minute:02d}:00"
            ET.SubElement(t, "Enabled").text = "true"
            if "Weekday" in entry:
                notes.append("StartCalendarInterval Weekday rendered as a daily "
                             "trigger; weekday filtering is not carried")
            ET.SubElement(ET.SubElement(t, "ScheduleByDay"), "DaysInterval").text = "1"

    if not len(root_triggers):
        notes.append("no trigger: the job has neither RunAtLoad, StartInterval "
                     "nor StartCalendarInterval, so nothing starts it")
    return notes


def _enabled():
    e = ET.Element("Enabled")
    e.text = "true"
    return e


def render(label, job):
    """(xml_string, losses, translations), each a list of plain sentences."""
    losses = []
    ET.register_namespace("", NS)
    task = ET.Element(f"{{{NS}}}Task", {"version": "1.2"})

    reg = ET.SubElement(task, "RegistrationInfo")
    ET.SubElement(reg, "URI").text = "\\" + label
    ET.SubElement(reg, "Description").text = f"Rendered from jobs.json ({label})"

    losses += triggers(job, ET.SubElement(task, "Triggers"))

    prin = ET.SubElement(ET.SubElement(task, "Principals"), "Principal", {"id": "Author"})
    ET.SubElement(prin, "LogonType").text = "InteractiveToken"
    ET.SubElement(prin, "RunLevel").text = "LeastPrivilege"

    st = ET.SubElement(task, "Settings")
    ET.SubElement(st, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(st, "StartWhenAvailable").text = "true"
    ET.SubElement(st, "ExecutionTimeLimit").text = "PT0S"
    if job.get("KeepAlive"):
        ET.SubElement(st, "RestartOnFailure")
        rof = st.find("RestartOnFailure")
        ET.SubElement(rof, "Interval").text = "PT1M"
        ET.SubElement(rof, "Count").text = "999"
        losses.append("KeepAlive is a supervisor that restarts on ANY exit; "
                      "RestartOnFailure only restarts on a non-zero exit")

    cmd, args, cmd_losses, translations = build_command(job)
    losses += cmd_losses
    if cmd is None:
        return None, losses, translations
    exe = ET.SubElement(ET.SubElement(task, "Actions", {"Context": "Author"}), "Exec")
    ET.SubElement(exe, "Command").text = cmd
    if args:
        ET.SubElement(exe, "Arguments").text = args
    if "WorkingDirectory" in job:
        ET.SubElement(exe, "WorkingDirectory").text = win_path(job["WorkingDirectory"])

    for key in sorted(set(job) - HANDLED):
        losses.append(f"{key}: " + NO_EQUIVALENT.get(key, "no Windows equivalent, dropped"))

    ET.indent(task, space="  ")
    return ('<?xml version="1.0" encoding="UTF-16"?>\n'
            + ET.tostring(task, encoding="unicode")), losses, translations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--into", default=None)
    a = ap.parse_args()

    jobs = json.load(open(MANIFEST))
    lossy, translated, clean, dead = {}, {}, 0, []

    if a.write and not a.into:
        print("--write needs --into DIR. There is no Windows LaunchAgents "
              "directory to default to, and guessing one is how a renderer "
              "writes 28 files nobody finds.", file=sys.stderr)
        return 2
    if a.write:
        os.makedirs(a.into, exist_ok=True)

    for label, job in sorted(jobs.items()):
        xml, losses, trans = render(label, job)
        if xml is None:
            dead.append(label)
        elif a.write:
            with open(os.path.join(a.into, label + ".xml"), "w", encoding="utf-16") as fh:
                fh.write(xml)
        if trans:
            translated[label] = trans
        if losses:
            lossy[label] = losses
        else:
            clean += 1

    if a.write:
        print(f"wrote {len(jobs) - len(dead)} task files into {a.into}")
        print("import each with:  schtasks /Create /TN \"<label>\" /XML <label>.xml")
        print()

    print(f"{len(jobs)} declared jobs: {clean} cross to Windows intact, "
          f"{len(lossy)} lose something, {len(dead)} cannot be rendered at all")
    print(f"{len(translated)} of them keep their environment and logs through a "
          f"cmd.exe wrapper, which is a translation and not a loss")
    for label in dead:
        print(f"\n  {label}\n      nothing to run")
    for label, losses in sorted(lossy.items()):
        print(f"\n  {label}")
        for l in losses:
            print(f"      - {l}")

    if lossy or dead:
        # Normalise the varying part out before counting, or "PATH has 21
        # entries" and "PATH has 4 entries" become two rows of one and the tally
        # stops being a tally.
        tally = {}
        for losses in lossy.values():
            for l in losses:
                key = re.sub(r"\d+", "N", re.sub(r"\([^)]*\)", "(...)",
                                                 l.split(";")[0].split(":")[0].strip()))
                tally[key] = tally.get(key, 0) + 1
        print("\nthe same few things, counted:")
        for reason, n in sorted(tally.items(), key=lambda kv: -kv[1]):
            print(f"    {n:3d} jobs   {reason}")
        print("\nEach line above is a guarantee the manifest makes that Windows "
              "does not keep.\nFixing the top row fixes the most jobs. This command "
              "is what counts them, so\nthe number moves when the work lands "
              "instead of when someone says it did.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
