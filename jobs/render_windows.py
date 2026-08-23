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
PLATFORMS = os.path.join(HERE, "platforms.json")
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"

# Keys this renderer honours. Anything in the manifest and not in here is
# reported against the job that uses it, every run.
HANDLED = {
    "label", "Program", "ProgramArguments", "WorkingDirectory",
    "StartInterval", "StartCalendarInterval", "RunAtLoad", "KeepAlive",
    "StandardOutPath", "StandardErrorPath", "EnvironmentVariables",
    "Nice", "ProcessType", "LowPriorityIO", "ThrottleInterval",
}

# Keys with no Task Scheduler equivalent at all. Named so the report says what
# was lost rather than how many things were lost.
NO_EQUIVALENT = {
    "WatchPaths": "Task Scheduler has no file-watch trigger. This job fires on a "
                  "path changing and cannot on Windows without a helper process.",
    "SoftResourceLimits": "no per-task rlimits.",
    "ExitTimeOut": "no configurable SIGTERM-to-SIGKILL gap.",
    "LimitLoadToSessionType": "no Aqua/Background session distinction.",
    "SteamContentPaths": "not a launchd key either; carried by mistake.",
}


VENV_BIN = re.compile(r"((?:^|/)\.?[\w.-]*venv)/bin/([\w.-]+)", re.I)


def venv_fix(s):
    """A virtualenv is bin/python on POSIX and Scripts\\python.exe on Windows.

    Not a guess about Windows: it is what `python -m venv` creates there. Doing
    the rewrite is a faithful translation. NOT doing it produced a path that
    looked right, did not exist, and sat inside the cmd.exe wrapper where the
    interpreter check could not see it, so twelve jobs reported clean and could
    not have run."""
    def one(m):
        exe = m.group(2)
        return f"{m.group(1)}/Scripts/{exe}" + ("" if "." in exe else ".exe")
    return VENV_BIN.sub(one, s)


def win_path(s):
    """{HOME} is %USERPROFILE% and POSIX separators are backslashes."""
    return venv_fix(s).replace("{HOME}", "%USERPROFILE%").replace("/", "\\")


def posix_only(cmd):
    """Does this command name a path that cannot exist on Windows?"""
    return cmd.startswith("/") or cmd.startswith("\\usr\\") or cmd.startswith("\\bin\\")


def _table():
    return json.load(open(PLATFORMS))["windows"]


def win_program(a, losses, trans):
    """Resolve a {PLACEHOLDER} program to the Windows one that runs it."""
    if not (a.startswith("{") and a.endswith("}")):
        return a
    name, t = a[1:-1], _table()
    if name in t["programs"]:
        got = t["programs"][name]
        if name in ("PYTHON3_SYSTEM", "PYTHON3_USER"):
            trans.append(f"{a} resolves to {got} from PATH. macOS has two "
                         f"pythons with different site-packages and Windows has "
                         f"one, so this job's dependencies must be installed for "
                         f"that interpreter")
        return got
    losses.append(f"{a}: platforms.json names no Windows program for it, so the "
                  f"task is generated and cannot run")
    return a


def win_search_path(k, entries, losses):
    """A search path is a list. Join it with ';' and say what did not survive.

    Windows finds its own system tools through its default PATH, so dropping
    /usr/bin and its neighbours is correct rather than lossy. Any OTHER absolute
    POSIX directory is a real loss, and it is named one entry at a time instead
    of condemning the whole variable."""
    t = _table()
    kept, lost = [], []
    for e in entries:
        if e in t["system_path_dirs"]:
            continue
        if e.startswith("{HOME}") or not e.startswith("/"):
            kept.append(win_path(e))
        else:
            lost.append(e)
    if lost:
        losses.append(f"{k} names {len(lost)} POSIX directory(ies) with no Windows "
                      f"equivalent, dropped from the search path: " + ", ".join(lost))
    return t["path_separator"].join(kept)


def build_command(job):
    """(command, arguments, losses, translations).

    Env vars and log redirection have no native Task Scheduler home, so they go
    through one cmd.exe wrapper rather than being dropped. That is a translation
    and it is stated, but it is NOT a loss -- counting it as one put all 28 jobs
    in the lossy column and made the headline number say nothing (LAW 28)."""
    argv = job.get("ProgramArguments") or ([job["Program"]] if "Program" in job else [])
    if not argv:
        return None, None, ["no Program or ProgramArguments; nothing to run"], []

    losses, trans = [], []
    # The check is on the program the job actually names. Running it after the
    # cmd.exe wrapper is chosen tests the wrapper, which is always portable, and
    # the whole class of unrunnable POSIX interpreters then reports clean.
    argv = [win_program(argv[0], losses, trans)] + list(argv[1:])
    argv = [win_path(a) for a in argv]
    if posix_only(argv[0]):
        losses.append(f"the program is a POSIX path ({argv[0]}); no such file exists "
                      f"on Windows, so this task is generated but cannot run until "
                      f"the interpreter is named portably")

    # A virtualenv puts its interpreter in bin/ on POSIX and in Scripts\ on
    # Windows. Turning the slashes round produces a path that looks fine and
    # does not exist, and because the real program sits inside the cmd.exe
    # wrapper the argv[0] check above never sees it. Reporting such a job clean
    # is exactly the confidently-wrong number this renderer is meant not to
    # produce, so it is named here.
    n = len(VENV_BIN.findall(json.dumps(job)))
    if n:
        trans.append(f"{n} virtualenv path(s) move from bin/ to Scripts\\ and the "
                     f"interpreter gains its .exe, which is where python -m venv "
                     f"puts them on Windows")

    env = dict(job.get("EnvironmentVariables") or {})
    out, err = job.get("StandardOutPath"), job.get("StandardErrorPath")

    for k, v in sorted(env.items()):
        if isinstance(v, list):
            env[k] = win_search_path(k, v, losses)
        elif isinstance(v, str) and v.count(":") >= 2 and "/" in v:
            losses.append(f"{k} is a colon-separated POSIX search path with "
                          f"{v.count(':') + 1} entries declared as one string; "
                          f"declare it as a list of directories in jobs.json and "
                          f"this renderer can join it with ';' instead")

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


def win_priority(job):
    """(priority, why). launchd says "run this low" three different ways.

    Nice, ProcessType: Background and LowPriorityIO are three controls for one
    intent, and Task Scheduler expresses that intent with <Priority>, where 0 is
    highest and 10 is lowest and 7 is the default. Carrying the intent is a
    translation. Insisting on three separate knobs Windows does not have would
    report three losses for a job that in fact schedules correctly."""
    said = []
    prio = 7
    nice = job.get("Nice")
    if nice is not None:
        prio = 10 if nice >= 10 else 8 if nice > 0 else 4 if nice < 0 else 7
        said.append(f"Nice {nice}")
    if job.get("ProcessType") == "Background":
        prio = max(prio, 10)
        said.append("ProcessType Background")
    if job.get("LowPriorityIO"):
        prio = max(prio, 10)
        said.append("LowPriorityIO")
    if not said:
        return 7, []
    return prio, [f"{' and '.join(said)} become Priority {prio} (0 is highest, "
                  f"10 is lowest, 7 is the default). Windows has one scheduling "
                  f"control where launchd has three"]


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
                # launchd counts Sunday as 0 or 7. Task Scheduler names the day.
                names = ["Sunday", "Monday", "Tuesday", "Wednesday",
                         "Thursday", "Friday", "Saturday"]
                w = ET.SubElement(t, "ScheduleByWeek")
                ET.SubElement(w, "WeeksInterval").text = "1"
                d = ET.SubElement(w, "DaysOfWeek")
                ET.SubElement(d, names[int(entry["Weekday"]) % 7])
            else:
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
    losses, translations_keepalive = [], []
    ET.register_namespace("", NS)
    task = ET.Element(f"{{{NS}}}Task", {"version": "1.2"})

    reg = ET.SubElement(task, "RegistrationInfo")
    ET.SubElement(reg, "URI").text = "\\" + label
    ET.SubElement(reg, "Description").text = f"Rendered from jobs.json ({label})"

    losses += triggers(job, ET.SubElement(task, "Triggers"))

    prin = ET.SubElement(ET.SubElement(task, "Principals"), "Principal", {"id": "Author"})
    ET.SubElement(prin, "LogonType").text = "InteractiveToken"
    ET.SubElement(prin, "RunLevel").text = "LeastPrivilege"

    # Task Scheduler validates <Settings> as an ordered sequence, so the order
    # below is not cosmetic. It is the order Task Scheduler itself uses when it
    # exports a task: the policy keys, then ExecutionTimeLimit, then Priority,
    # then RestartOnFailure last. Nothing here has been imported on Windows yet,
    # so this ordering is the part of the renderer the windows-rebuild drill
    # exists to check.
    st = ET.SubElement(task, "Settings")
    ET.SubElement(st, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(st, "StartWhenAvailable").text = "true"
    ET.SubElement(st, "ExecutionTimeLimit").text = "PT0S"
    prio, why = win_priority(job)
    if why:
        ET.SubElement(st, "Priority").text = str(prio)
    if job.get("KeepAlive"):
        rof = ET.SubElement(st, "RestartOnFailure")
        ET.SubElement(rof, "Interval").text = "PT1M"
        ET.SubElement(rof, "Count").text = "999"
        # RestartOnFailure alone only fires on a non-zero exit, and KeepAlive
        # restarts on ANY exit. The rest of the supervisor is the trigger:
        # every task here sets MultipleInstancesPolicy=IgnoreNew, so a trigger
        # that re-fires on a gap starts the job when it has stopped and is
        # ignored while it is still running. That IS KeepAlive, with the gap as
        # its latency, and the gap is where ThrottleInterval lands too.
        gap = max(60, int(job.get("ThrottleInterval") or 0))
        for t in task.find("Triggers"):
            if t.find("Repetition") is None:
                rep = ET.SubElement(t, "Repetition")
                ET.SubElement(rep, "Interval").text = f"PT{gap}S"
                ET.SubElement(rep, "StopAtDurationEnd").text = "false"
        declared = job.get("ThrottleInterval")
        translations_keepalive.append(
            f"KeepAlive becomes IgnoreNew plus a trigger that re-fires every "
            f"{gap}s, so a job that has stopped is restarted within {gap}s "
            f"whatever its exit code" + (
                f". ThrottleInterval is {declared}s and Task Scheduler's "
                f"repetition floor is 60s, so the respawn gap is {gap}s"
                if declared and declared < 60 else ""))

    cmd, args, cmd_losses, translations = build_command(job)
    translations += translations_keepalive + why
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
