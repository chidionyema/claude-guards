#!/usr/bin/env python3
"""A durable multi-step job runner for agent work, built on LangGraph.

Why this exists. Every long agent job on this estate dies the same way: the laptop reboots,
a Fly machine goes, a session is compacted away, and the job restarts from step 0 because
nothing wrote down which step it had reached. prospector's own resume has this shape --
`prospector/run.py:2743-2745` says it "re-runs the full verification pipeline (not partial)".

What this gives you instead. Every step is committed to sqlite the moment it finishes. Kill
the process at any point and re-run it with the same --job id: it starts at the first step
that has not completed. A step marked `gate` stops the run and waits for a person; answer it
with --approve or --reject and the run carries on from there.

Run it:
  durable_job.py --job build-42 --steps steps.json      # start or resume
  durable_job.py --job build-42 --status                # where did it get to
  durable_job.py --job build-42 --approve               # release a human gate
  durable_job.py --selftest                             # prove the whole thing

steps.json is a list. Each entry is one of:
  {"name": "compile",  "run": "make -j4"}          a shell command; non-zero exit fails the job
  {"name": "sign off", "gate": "ship to prod?"}    stops and waits for a person

The state lives in ~/.claude/state/coord/jobs.sqlite and outlives the process, the session
and the machine.

One thing to design around. A checkpoint is committed when a step RETURNS, so a step that was
half-way through when the process died runs again from its start. Committed steps never run
again. That makes shell steps at-least-once, which is the same guarantee Temporal and Airflow
give and for the same reason: a shell command cannot report how far it got. Write steps that
are safe to repeat -- `mkdir -p`, `rsync`, an upsert -- not `count += 1`.
"""

from __future__ import annotations

# Before any langchain import. langsmith is a hard dependency of langchain-core and will send
# traces to a paid service if these are unset and a key is ever present in the environment.
# This company has no funds, so the runner refuses tracing at the source rather than trusting
# the environment to be clean.
import os

for _var in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
    os.environ[_var] = "false"
os.environ.pop("LANGSMITH_API_KEY", None)
os.environ.pop("LANGCHAIN_API_KEY", None)

import argparse
import json
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

DB = Path.home() / ".claude" / "state" / "coord" / "jobs.sqlite"


def _keep_last(_old: Any, new: Any) -> Any:
    return new


def _extend(old: list, new: list) -> list:
    return (old or []) + (new or [])


class JobState(TypedDict):
    steps: Annotated[list, _keep_last]
    cursor: Annotated[int, _keep_last]
    results: Annotated[list, _extend]
    failed: Annotated[str | None, _keep_last]


def _run_shell(cmd: str, timeout: int) -> dict:
    started = time.time()
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return {
        "exit": p.returncode,
        "seconds": round(time.time() - started, 3),
        "stdout": p.stdout[-2000:],
        "stderr": p.stderr[-2000:],
    }


def _step_node(state: JobState) -> dict:
    """Execute exactly one step. Returning from this function is what commits a checkpoint."""
    i = state["cursor"]
    step = state["steps"][i]
    name = step.get("name") or f"step-{i}"

    if "gate" in step:
        # Suspends the whole run and persists. The process may exit here; the answer arrives
        # later, from another process, possibly after a reboot.
        answer = interrupt({"step": name, "asks": step["gate"]})
        ok = bool(answer) and str(answer).lower() not in ("no", "false", "reject", "rejected")
        rec = {"step": name, "kind": "gate", "answer": answer, "ok": ok}
        return {
            "cursor": i + 1,
            "results": [rec],
            "failed": None if ok else f"{name}: rejected",
        }

    out = _run_shell(step["run"], timeout=int(step.get("timeout", 900)))
    rec = {"step": name, "kind": "shell", **out}
    return {
        "cursor": i + 1,
        "results": [rec],
        "failed": None if out["exit"] == 0 else f"{name}: exit {out['exit']}",
    }


def _next(state: JobState) -> str:
    if state.get("failed"):
        return END
    return "step" if state["cursor"] < len(state["steps"]) else END


def build_graph(checkpointer):
    g = StateGraph(JobState)
    g.add_node("step", _step_node)
    # An empty job must terminate rather than index past the end of the list.
    g.add_conditional_edges(START, _next, {"step": "step", END: END})
    g.add_conditional_edges("step", _next, {"step": "step", END: END})
    return g.compile(checkpointer=checkpointer)


def _config(job: str) -> dict:
    return {"configurable": {"thread_id": job}}


def _drive(app, job: str, payload) -> dict:
    """Run until the graph finishes or hits a gate. Returns the last state."""
    for _ in app.stream(payload, _config(job), stream_mode="values"):
        pass
    return app.get_state(_config(job))


def cmd_run(job: str, steps_file: str | None) -> int:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(DB)) as saver:
        app = build_graph(saver)
        snap = app.get_state(_config(job))
        if snap.values:
            done = snap.values.get("cursor", 0)
            total = len(snap.values.get("steps", []))
            print(f"resuming {job}: {done}/{total} steps already committed", flush=True)
            if done < total and not snap.interrupts:
                nxt = snap.values["steps"][done].get("name") or f"step-{done}"
                # The process died somewhere. Everything committed is safe and will not run
                # again; the step it was in the middle of has no way to know how far it got,
                # so it starts over. Shell steps are at-least-once and must be safe to repeat.
                print(f"  step {done + 1} ('{nxt}') was in flight when the last process "
                      f"ended -- it runs again from the start", flush=True)
            payload = None
        else:
            if not steps_file:
                print(f"job {job} is new and no --steps was given", file=sys.stderr)
                return 2
            steps = json.loads(Path(steps_file).read_text())
            print(f"starting {job}: {len(steps)} steps", flush=True)
            payload = {"steps": steps, "cursor": 0, "results": [], "failed": None}
        st = _drive(app, job, payload)
        return _report(st)


def cmd_answer(job: str, answer) -> int:
    with SqliteSaver.from_conn_string(str(DB)) as saver:
        app = build_graph(saver)
        st = app.get_state(_config(job))
        if not st.interrupts:
            print(f"job {job} is not waiting on a gate", file=sys.stderr)
            return 2
        st = _drive(app, job, Command(resume=answer))
        return _report(st)


def _report(st) -> int:
    v = st.values or {}
    done, total = v.get("cursor", 0), len(v.get("steps", []))
    for r in v.get("results", []):
        mark = "ok " if r.get("ok", r.get("exit") == 0) else "FAIL"
        print(f"  [{mark}] {r['step']}")
    if st.interrupts:
        q = st.interrupts[0].value
        print(f"WAITING at {done}/{total} -- gate '{q['step']}' asks: {q['asks']}")
        print(f"  answer it: durable_job.py --job {shlex.quote(_thread(st))} --approve")
        return 3
    if v.get("failed"):
        print(f"FAILED at {done}/{total}: {v['failed']}")
        return 1
    print(f"DONE {done}/{total}")
    return 0


def _thread(st) -> str:
    return st.config.get("configurable", {}).get("thread_id", "?")


def cmd_status(job: str) -> int:
    if not DB.exists():
        print("no jobs yet", file=sys.stderr)
        return 2
    with SqliteSaver.from_conn_string(str(DB)) as saver:
        app = build_graph(saver)
        st = app.get_state(_config(job))
        if not st.values:
            print(f"no such job: {job}", file=sys.stderr)
            return 2
        return _report(st)


def cmd_list() -> int:
    if not DB.exists():
        print("no jobs yet")
        return 0
    con = sqlite3.connect(str(DB))
    rows = con.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id").fetchall()
    con.close()
    for (t,) in rows:
        print(t)
    return 0


def selftest() -> int:
    """Prove the three claims this file makes, without touching the real database."""
    import tempfile

    global DB
    failures = []

    def check(name, cond, detail=""):
        print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:
        DB = Path(td) / "t.sqlite"
        marker = Path(td) / "ran.txt"

        # 1. an empty job terminates instead of indexing past the end
        with SqliteSaver.from_conn_string(str(DB)) as s:
            app = build_graph(s)
            st = _drive(app, "empty", {"steps": [], "cursor": 0, "results": [], "failed": None})
            check("empty job terminates", st.values["cursor"] == 0 and not st.interrupts)

        # 2. a failing step stops the job and does not run the step after it
        steps = [
            {"name": "a", "run": f"echo a >> {marker}"},
            {"name": "b", "run": "exit 7"},
            {"name": "c", "run": f"echo c >> {marker}"},
        ]
        with SqliteSaver.from_conn_string(str(DB)) as s:
            app = build_graph(s)
            st = _drive(app, "fail", {"steps": steps, "cursor": 0, "results": [], "failed": None})
            body = marker.read_text() if marker.exists() else ""
            check("failing step stops the job", st.values["failed"] == "b: exit 7")
            check("the step after a failure does not run", "c" not in body, f"marker={body!r}")

        # 3. a gate suspends, survives a fresh process-level open, and resumes
        marker.unlink(missing_ok=True)
        steps = [
            {"name": "before", "run": f"echo before >> {marker}"},
            {"name": "ask", "gate": "carry on?"},
            {"name": "after", "run": f"echo after >> {marker}"},
        ]
        with SqliteSaver.from_conn_string(str(DB)) as s:
            st = _drive(build_graph(s), "gate", {"steps": steps, "cursor": 0, "results": [], "failed": None})
            check("a gate suspends the run", bool(st.interrupts) and st.values["cursor"] == 1)
            check("nothing past the gate ran", "after" not in marker.read_text())
        # a completely new saver and a new graph object, as a new process would build
        with SqliteSaver.from_conn_string(str(DB)) as s:
            st = _drive(build_graph(s), "gate", Command(resume="yes"))
            body = marker.read_text()
            check("resume finishes the job", st.values["cursor"] == 3 and not st.values["failed"])
            check("the step before the gate did not re-run", body.count("before") == 1, f"marker={body!r}")
            check("the step after the gate ran once", body.count("after") == 1, f"marker={body!r}")

    print(f"\n{'ALL PASS' if not failures else 'FAILURES: ' + ', '.join(failures)}")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="job id; the same id resumes the same job")
    ap.add_argument("--steps", help="path to a steps json file, for a new job")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--reject", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.list:
        return cmd_list()
    if not a.job:
        ap.error("--job is required")
    if a.status:
        return cmd_status(a.job)
    if a.approve or a.reject:
        return cmd_answer(a.job, "yes" if a.approve else "no")
    return cmd_run(a.job, a.steps)


if __name__ == "__main__":
    sys.exit(main())
