#!/usr/bin/env python3
"""Run the estate's recovery drills and record which ones actually pass.

A drill is a command that proves a recovery path still works: a rebuild, a
restore, a rollback, a rotation. LAW 19 grades every dependency by its exit, and
an exit that has never been taken is a hope. This is the register of those exits
and the date each one last ran green.

    run.py --list        what is registered and when each last passed
    run.py --all         run every drill that has a command
    run.py --run <id>    run one
    run.py --check       exit 1 if a drill is failing or has gone stale

--all and --check post one line to ESTATE_BOARD.jsonl, which every session is
handed at startup, so PASS and NOT-RUN are different lines somebody reads rather
than two kinds of silence (LAW 28, LAW 31).

Drills with no command yet are listed as NOT WRITTEN with the thing that needs
writing. They are counted in every report and they do NOT make --check red: a
gate that is red forever is a gate people stop reading, which is the failure this
file exists to stop.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTER = os.path.join(HERE, "register.json")
STATE = os.path.expanduser("~/.claude/state/drills.jsonl")
TIMEOUT = 900


def load():
    with open(REGISTER) as fh:
        return json.load(fh)


def history():
    """{id: newest record} from the append-only log."""
    out = {}
    if not os.path.exists(STATE):
        return out
    with open(STATE) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("status") == "PASS" or r["id"] not in out:
                out[r["id"]] = r
            elif out[r["id"]].get("ts", 0) <= r.get("ts", 0):
                out[r["id"]] = r
    return out


def last_green(rid):
    """The newest PASS for one drill, or None. Kept separate from the newest
    record: a drill that passed on Monday and failed today has both facts, and
    the age of the last green is the one that says how exposed we are."""
    if not os.path.exists(STATE):
        return None
    best = None
    with open(STATE) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("id") == rid and r.get("status") == "PASS":
                if best is None or r.get("ts", 0) > best.get("ts", 0):
                    best = r
    return best


def status_of(d, reg):
    """(status, detail) for one registered drill, without running it."""
    if not d.get("cmd"):
        return "NOT WRITTEN", d.get("todo", "")
    green = last_green(d["id"])
    newest = history().get(d["id"])
    if newest and newest.get("status") == "FAIL":
        return "FAIL", newest.get("note", "")
    if green is None:
        return "NEVER RUN", ""
    age_d = (time.time() - green["ts"]) / 86400
    cap = d.get("max_age_days", reg.get("max_age_days_default", 8))
    if age_d > cap:
        return "STALE", f"last green {age_d:.1f}d ago, bar is {cap}d"
    return "PASS", f"{age_d:.1f}d ago"


def run_one(d):
    cmd = [c.replace("{HERE}", HERE).replace("{HOME}", os.path.expanduser("~"))
           for c in d["cmd"]]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        rc, tail = p.returncode, (p.stdout + p.stderr).strip().splitlines()
    except subprocess.TimeoutExpired:
        rc, tail = 124, [f"timed out after {TIMEOUT}s"]
    note = tail[-1][:300] if tail else ""
    rec = {"ts": int(time.time()),
           "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "id": d["id"], "status": "PASS" if rc == 0 else "FAIL",
           "rc": rc, "seconds": round(time.time() - t0, 1), "note": note}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def post(kind, text):
    try:
        sys.path.insert(0, os.path.dirname(HERE))
        import tracked
        tracked.board(kind, text, "drills")
    except Exception:
        pass


def table(reg):
    print(f"{'drill':<24} {'status':<12} detail")
    counts = {}
    for d in reg["drills"]:
        st, detail = status_of(d, reg)
        counts[st] = counts.get(st, 0) + 1
        print(f"  {d['id']:<22} {st:<12} {detail[:70]}")
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--run")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    reg = load()

    if a.run:
        d = next((x for x in reg["drills"] if x["id"] == a.run), None)
        if d is None:
            sys.exit(f"no drill called {a.run}")
        if not d.get("cmd"):
            print(f"{a.run}: NOT WRITTEN. {d.get('todo','')}")
            return 2
        rec = run_one(d)
        print(f"{rec['id']}  {rec['status']}  rc={rec['rc']}  {rec['seconds']}s  {rec['note']}")
        return 0 if rec["status"] == "PASS" else 1

    if a.all:
        results = [run_one(d) for d in reg["drills"] if d.get("cmd")]
        unwritten = [d["id"] for d in reg["drills"] if not d.get("cmd")]
        failed = [r for r in results if r["status"] == "FAIL"]
        for r in results:
            print(f"  {r['id']:<22} {r['status']:<6} rc={r['rc']:<4} {r['seconds']}s  {r['note'][:80]}")
        if failed:
            post("drills-failed",
                 f"{len(failed)} of {len(results)} recovery drills failed: "
                 + "; ".join(f"{r['id']} ({r['note'][:80]})" for r in failed)
                 + f". {len(unwritten)} more recovery paths have no drill at all: "
                 + ", ".join(unwritten) + ".")
        else:
            post("drills-passed",
                 f"All {len(results)} written recovery drills passed. "
                 f"{len(unwritten)} recovery paths still have no drill and are therefore "
                 f"unproven: " + ", ".join(unwritten) + ".")
        print()
        return 1 if failed else 0

    if a.check:
        counts = table(reg)
        broken = counts.get("FAIL", 0) + counts.get("STALE", 0) + counts.get("NEVER RUN", 0)
        print(f"\n{counts.get('PASS', 0)} passing, {broken} needing a run, "
              f"{counts.get('NOT WRITTEN', 0)} with no drill written")
        return 1 if broken else 0

    table(reg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
