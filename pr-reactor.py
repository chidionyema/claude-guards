#!/usr/bin/env python3
"""A red pull request gets a reaction, not a colour on a page nobody opens.

WHY THIS EXISTS (founder, 2026-08-21): "also failed prs should alert and get a
reaction/respone", "we dont react to falied pprs", "blind spot", "this is with all
alerts that dot self heal", "we need to close loops asap", "to buld it in".

THE MEASURED BLIND SPOT. `scripts/pr_triage.py` on main already reads the CAUSE of a red
pull request correctly -- ghost runs, killed runners, real test failures, conflicts. It is
excellent and it is registered in the ops console as a BUTTON A HUMAN PRESSES. Measured
2026-08-21: no cron entry, no launchd plist, no workflow runs it. So the estate can
diagnose a red pull request perfectly and never does.

And a single press does not help, because the answer rots. Measured inside four minutes on
2026-08-21: #538 went REAL FAIL -> a fix pushed -> a run in flight, and #533 went REAL FAIL
-> NO RUN. Any report older than a few minutes describes a world that has moved.

THE LADDER, which is LAW 6's and is the whole design:

  1. SELF-HEAL   A run that died of infrastructure -- killed runner, cancelled by another
                 push, a ghost run with no jobs, no run at all -- needs no person. Re-run
                 it. Capped, so a genuinely broken thing cannot spin CI forever.
  2. ALERT       A REAL FAIL or a CONFLICT needs a person. It goes on the estate board with
                 the CAUSE attached, so the next session inherits the diagnosis instead of
                 re-deriving it.
  3. ONCE        Keyed on (pull request, head commit, verdict). The same state never alerts
                 twice. This estate has already measured what repetition does to a channel:
                 314 peer messages in 24 hours, half of them acknowledgements, and the
                 founder's verdict was "it keeps everyone looping over the same issues".
                 A new commit is a new state and may alert again.

WHAT IT WILL NEVER DO. Merge, close, push, or force anything. Re-running a job is free and
reversible; the rest is not, and LAW 11 says those are not mine to decide alone.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE = Path.home() / ".claude" / "state" / "pr-reactor.json"
BOARD = Path.home() / ".claude" / "ESTATE_BOARD.jsonl"
REPO_DIR = Path("/Users/chidionyema/Documents/code/prospector")

# A run that failed for its own reasons needs a person. A run that failed because the
# machinery under it broke needs a re-run, and the estate has measured that distinction:
# of 27 red pull requests on 2026-08-19, four had a test failure and nine were a machine
# dying mid-build. Treating those nine as code failures cost real hours.
SELF_HEAL = {
    "RUNNER KILLED": "the runner died mid-build; the code was never graded",
    "CANCELLED":     "another push cancelled this run; nothing was graded",
    "GHOST ONLY":    "a bot push minted a zero-job run; nothing was graded",
    "NO RUN":        "no CI run exists at this head",
    "MERGE UNKNOWN": "CI is green; GitHub has not finished computing mergeability",
}
NEEDS_A_PERSON = {"REAL FAIL", "CONFLICT"}
NOTHING_TO_DO = {"GREEN", "IN PROGRESS"}

# Two attempts, then stop and say so. A third re-run of the same commit has never once
# produced a different answer, and CI minutes are money this company does not have (LAW 14).
MAX_HEALS = 2
# A person-needing pull request that is still red after this long says so again, once.
# Long enough not to nag, short enough that "close loops asap" means something.
ESCALATE_AFTER_S = 45 * 60


# ---------------------------------------------------------------- state

def load_state(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}      # a lost state file costs one duplicate alert, never a missed one


def save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".prr-", suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
    except Exception:
        pass


def key_for(pr: dict) -> str:
    """A state is a pull request at a commit with a verdict. Any of the three changing is a
    new state that deserves a fresh reaction -- especially the commit, because a new commit
    is the author answering the last alert."""
    return "%s@%s:%s" % (pr.get("pr"), (pr.get("sha") or "")[:12], pr.get("verdict"))


# ---------------------------------------------------------------- the decision (pure)

def plan(prs: "list[dict]", state: dict, now: float) -> "list[dict]":
    """What to do about each pull request. Pure: no network, no clock, no disk.

    Everything that decides an action lives here so the selftest can grade the decision
    rather than grading a mock of the thing that carries it out.
    """
    out = []
    for p in prs:
        v, k = p.get("verdict"), key_for(p)
        seen = state.get(k) or {}
        heals = int(seen.get("heals") or 0)
        alerted_at = float(seen.get("alerted_at") or 0)

        if v in NOTHING_TO_DO:
            act, why = "none", "moving on its own"
        elif v == "DRAFT":
            # Green and drafted is a loop nobody is holding: CI has nothing left to say and
            # the pull request still cannot merge. It is not a failure, so it never re-runs;
            # it is a nudge, and it goes out exactly once per commit.
            act, why = ("none", "already said") if alerted_at else \
                       ("alert", "green but drafted; only the author can mark it ready")
        elif v in SELF_HEAL:
            if heals >= MAX_HEALS:
                # Re-running the same commit a third time is not persistence, it is a loop.
                # Escalate to a person, because self-healing has now been proved not to work.
                act, why = ("alert", "re-run %d times and still %s; this is not infrastructure"
                            % (heals, v)) if not alerted_at else ("none", "already escalated")
            else:
                act, why = "heal", SELF_HEAL[v]
        elif v in NEEDS_A_PERSON:
            if not alerted_at:
                act, why = "alert", p.get("detail") or v
            elif now - alerted_at >= ESCALATE_AFTER_S:
                act, why = "alert", "STILL %s after %d minutes: %s" % (
                    v, int((now - alerted_at) // 60), p.get("detail") or "")
            else:
                act, why = "none", "already alerted"
        else:
            # An unknown verdict is not a silence. A new verdict added to pr_triage must
            # surface here rather than being dropped because this table has not caught up.
            act, why = ("alert", "unrecognised verdict %r -- pr-reactor needs a rule for it") \
                if not alerted_at else ("none", "already alerted")

        out.append({"pr": p.get("pr"), "branch": p.get("branch"), "verdict": v,
                    "sha": p.get("sha"), "run": p.get("run"), "key": k,
                    "action": act, "why": why, "heals": heals})
    return out


def apply_plan(planned: "list[dict]", state: dict, now: float,
               heal, alert) -> "list[dict]":
    """Carry out a plan. `heal` and `alert` are injected so the selftest never touches
    the network. A step that raises is recorded as failed and does NOT stop the rest --
    one unreachable pull request must not silence every other."""
    done = []
    for item in planned:
        k, act = item["key"], item["action"]
        rec = dict(state.get(k) or {})
        rec.setdefault("first_seen", now)
        try:
            if act == "heal":
                ok = bool(heal(item))
                rec["heals"] = int(rec.get("heals") or 0) + 1
                rec["last_heal"] = now
                item["result"] = "re-run requested" if ok else "re-run REFUSED by GitHub"
                if not ok:
                    # A re-run GitHub will not accept is not a heal. Do not let a failed
                    # attempt burn the cap and then look like two honest tries.
                    rec["heals"] -= 1
            elif act == "alert":
                alert(item)
                rec["alerted_at"] = now
                item["result"] = "alerted"
            else:
                item["result"] = "none"
        except Exception as exc:
            item["result"] = "ERROR: %s" % exc
        state[k] = rec
        done.append(item)
    return done


# ---------------------------------------------------------------- the world

def _gh(args: "list[str]", cwd: Path = REPO_DIR, timeout: int = 120):
    p = subprocess.run(["gh"] + args, cwd=str(cwd), capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def read_prs() -> "list[dict]":
    """pr_triage is the diagnosis and this does NOT reimplement it (LAW 3). It adds the one
    field the reactor needs and triage does not report: the head commit, which is what makes
    an alert once-per-state rather than once-per-run."""
    py = REPO_DIR / ".venv" / "bin" / "python"
    p = subprocess.run([str(py), "scripts/pr_triage.py", "--json"], cwd=str(REPO_DIR),
                       capture_output=True, text=True, timeout=600)
    if not p.stdout.strip():
        raise RuntimeError("pr_triage produced nothing: %s" % (p.stderr or "")[-200:])
    data = json.loads(p.stdout)
    rc, out, _ = _gh(["pr", "list", "--state", "open", "--limit", "100",
                      "--json", "number,headRefOid"])
    sha = {}
    if rc == 0 and out.strip():
        sha = {r["number"]: r["headRefOid"] for r in json.loads(out)}
    prs = data.get("prs") or []
    for r in prs:
        r["sha"] = sha.get(r.get("pr"), "")
    return prs


def do_heal(item: dict) -> bool:
    """Ask GitHub to run CI again at this head. Never pushes, never merges."""
    run_id = item.get("run")
    if item["verdict"] in ("NO RUN", "GHOST ONLY") or not run_id:
        # Nothing to re-run: there is no real run. Dispatch the workflow at the branch.
        rc, _, err = _gh(["workflow", "run", "ci.yml", "--ref", item["branch"]])
        if rc != 0:
            print("    dispatch refused: %s" % (err or "").strip()[:160])
        return rc == 0
    rc, _, err = _gh(["run", "rerun", str(run_id), "--failed"])
    if rc != 0:
        # A run with no failed jobs cannot be re-run "--failed"; ask for the whole run.
        rc, _, err = _gh(["run", "rerun", str(run_id)])
    if rc != 0:
        print("    re-run refused: %s" % (err or "").strip()[:160])
    return rc == 0


def do_alert(item: dict) -> None:
    """Put it where every session already looks. The estate board is handed to each session
    at start-up, so ONE row reaches every agent -- which is the cheap half of LAW 10, and the
    half that does not add to the message traffic the founder already called too noisy."""
    text = ("PR #%s (%s) is %s and needs a person. CAUSE: %s. "
            "Diagnosis: cd %s && .venv/bin/python scripts/pr_triage.py"
            % (item["pr"], item["branch"], item["verdict"], item["why"], REPO_DIR))
    row = {"session": "pr-reactor", "to": "*", "ts": time.time(), "text": text,
           "tokens": ["#%s" % item["pr"], item["branch"], item["verdict"]]}
    try:
        BOARD.parent.mkdir(parents=True, exist_ok=True)
        with BOARD.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as exc:
        print("    board write failed: %s" % exc)
    print("    ALERT: %s" % text[:150])


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    fails = []

    def ck(name, cond):
        print("  %-62s %s" % (name, "ok" if cond else "FAIL"))
        if not cond:
            fails.append(name)

    def pr(n, verdict, sha="aaaaaaaaaaaa", run=1, detail="d", branch="b"):
        return {"pr": n, "verdict": verdict, "sha": sha, "run": run,
                "detail": detail, "branch": branch}

    T = 1_000_000.0

    # --- the ladder ----------------------------------------------------------
    p = plan([pr(1, "GREEN"), pr(2, "IN PROGRESS")], {}, T)
    ck("a green or in-flight pull request is left alone",
       [x["action"] for x in p] == ["none", "none"])

    p = plan([pr(3, "RUNNER KILLED"), pr(4, "CANCELLED"),
              pr(5, "GHOST ONLY"), pr(6, "NO RUN"), pr(7, "MERGE UNKNOWN")], {}, T)
    ck("every infrastructure failure self-heals, none of them alert",
       [x["action"] for x in p] == ["heal"] * 5)

    p = plan([pr(8, "REAL FAIL"), pr(9, "CONFLICT")], {}, T)
    ck("a real failure and a conflict alert, and never re-run",
       [x["action"] for x in p] == ["alert", "alert"])
    ck("the alert carries the CAUSE, not just the colour", p[0]["why"] == "d")

    # --- once, and only once -------------------------------------------------
    st = {}
    apply_plan(plan([pr(8, "REAL FAIL")], st, T), st, T, lambda i: True, lambda i: None)
    ck("the same failure at the same commit does not alert twice",
       plan([pr(8, "REAL FAIL")], st, T + 60)[0]["action"] == "none")
    ck("a NEW commit on the same pull request alerts again",
       plan([pr(8, "REAL FAIL", sha="bbbbbbbbbbbb")], st, T + 60)[0]["action"] == "alert")
    ck("the same commit reaching a NEW verdict alerts again",
       plan([pr(8, "CONFLICT")], st, T + 60)[0]["action"] == "alert")
    ck("a pull request still red after the escalation window says so once more",
       plan([pr(8, "REAL FAIL")], st, T + ESCALATE_AFTER_S + 1)[0]["action"] == "alert")
    ck("and not one minute before that window",
       plan([pr(8, "REAL FAIL")], st, T + ESCALATE_AFTER_S - 60)[0]["action"] == "none")

    # --- the re-run cap ------------------------------------------------------
    st2, calls = {}, []
    for _ in range(4):
        apply_plan(plan([pr(10, "RUNNER KILLED")], st2, T), st2, T,
                   lambda i: calls.append(i["pr"]) or True, lambda i: None)
    ck("a re-run is capped, so a broken thing cannot spin CI forever",
       len(calls) == MAX_HEALS)
    ck("hitting the cap escalates to a person instead of going quiet",
       any(v.get("alerted_at") for v in st2.values()))

    # A re-run GitHub refuses is not an attempt. Two refusals must not consume the cap.
    st3, tried = {}, []
    for _ in range(3):
        apply_plan(plan([pr(11, "CANCELLED")], st3, T), st3, T,
                   lambda i: tried.append(1) or False, lambda i: None)
    ck("a REFUSED re-run does not burn the cap", len(tried) == 3)

    # --- drafts --------------------------------------------------------------
    st4 = {}
    p = plan([pr(12, "DRAFT")], st4, T)
    ck("a green drafted pull request is nudged, not re-run", p[0]["action"] == "alert")
    apply_plan(p, st4, T, lambda i: True, lambda i: None)
    ck("the draft nudge is not repeated",
       plan([pr(12, "DRAFT")], st4, T + ESCALATE_AFTER_S * 3)[0]["action"] == "none")

    # --- an unknown verdict must never be silence -----------------------------
    p = plan([pr(13, "SOMETHING NEW")], {}, T)
    ck("a verdict this table does not know alerts rather than being dropped",
       p[0]["action"] == "alert" and "unrecognised" in p[0]["why"])

    # --- one broken pull request must not silence the others -------------------
    st5 = {}
    def boom(i):
        raise RuntimeError("github is down")
    done = apply_plan(plan([pr(14, "REAL FAIL"), pr(15, "REAL FAIL", sha="cccccccccccc")],
                           st5, T), st5, T, lambda i: True, boom)
    ck("an alert that throws is recorded and the next one still runs",
       len(done) == 2 and all(x["result"].startswith("ERROR") for x in done))
    ck("a failed alert is not recorded as delivered",
       all(not (st5[x["key"]].get("alerted_at")) for x in done))

    # --- state file ------------------------------------------------------------
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / "s.json"
        save_state(sp, {"a": {"heals": 1}})
        ck("state survives a round trip", load_state(sp) == {"a": {"heals": 1}})
        sp.write_text("{ not json")
        ck("a corrupt state file is not fatal", load_state(sp) == {})
        ck("a missing state file is not fatal", load_state(Path(d) / "nope.json") == {})

    print("\n%d checks, %d failed" % (20, len(fails)))
    return 1 if fails else 0


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="say what it would do and change nothing")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    state = load_state(STATE)
    now = time.time()
    try:
        prs = read_prs()
    except Exception as exc:
        # A reactor that cannot see is worse than one that is not running, because it looks
        # like "nothing is wrong". Say so loudly and exit non-zero.
        print("pr-reactor CANNOT SEE: %s" % exc, file=sys.stderr)
        return 2

    planned = plan(prs, state, now)
    for i in planned:
        print("#%-4s %-14s %-34s %s: %s" % (i["pr"], i["verdict"], i["branch"][:34],
                                            i["action"].upper(), i["why"][:70]))
    if a.dry_run:
        print("\n(dry run: nothing was changed)")
        return 0

    done = apply_plan(planned, state, now, do_heal, do_alert)
    save_state(STATE, state)
    acted = [d for d in done if d["action"] != "none"]
    print("\n%d pull request(s), %d reaction(s): %d healed, %d alerted" % (
        len(done), len(acted),
        sum(1 for d in acted if d["action"] == "heal"),
        sum(1 for d in acted if d["action"] == "alert")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
