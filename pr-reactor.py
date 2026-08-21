#!/usr/bin/env python3
"""A red pull request gets a reaction, not a colour on a page nobody opens.

WHY THIS EXISTS (founder, 2026-08-21): "also failed prs should alert and get a
reaction/respone", "we dont react to falied pprs", "blind spot", "this is with all
alerts that dot self heal", "we need to close loops asap", "to buld it in".

WHAT IT DOES NOT DO, AND WHY THAT IS THE DESIGN. It repairs nothing. Every self-healing
repair a red pull request can want already has an owner in the repository, and I very
nearly wrote a second copy of all of them:

  NO RUN, CANCELLED, stale, a build REFUSED because main was red
      -> `.github/workflows/pr-keeper.yml` (read on origin/main, 2026-08-21)
  GHOST ONLY / action_required
      -> `.github/workflows/approve-parked-runs.yml`, every 10 minutes

Two implementations of one repair is how pull request #426 became unmergeable: each had
passing tests, so neither could be deleted without deleting tested work. So this reacts
to the two things that genuinely have no owner, and WATCHES the ones that do.

  1. ALERT      REAL FAIL and CONFLICT. pr-keeper deliberately refuses to touch these --
                "re-run a REFUSAL, never a FAILURE", and it is right, a real test failure
                is the author's. But nothing anywhere tells the author. That silence IS
                the founder's blind spot. A green DRAFT is the same shape: pr-keeper skips
                drafts, so a pull request that has finished CI can sit forever.

  2. WATCHDOG   A verdict that HAS an owner is left alone -- until it has sat unchanged
                past the grace window, at which point the owner is provably not firing and
                that is itself the alert. Measured today, this is not hypothetical:
                pr-keeper has no `schedule:` at all. It runs on a pull request event, or
                when main's CI goes green, and otherwise never. A run killed at 03:00 with
                main already green waits for the next person to push something.

  3. ONCE       Keyed on (pull request, head commit, verdict), and it reads the estate
                board first: if any session raised "#<n>" in the last 45 minutes it stays
                quiet and inherits THEIR timestamp, so the loop still closes if they go
                silent. The founder's complaint about the peer channel was never volume,
                it was the same issue arriving again -- 314 messages in 24 hours, half of
                them acknowledgements. A robot on that channel must be the quietest voice.

It never merges, closes, pushes, re-runs or dispatches anything. It reads GitHub and it
appends one line to a file. That is the whole blast radius.

Why the earlier version's repairs were cut, beyond the duplication: `gh workflow run ci.yml`
fires `workflow_dispatch`, and `ci.yml:313` gives the `guard` job `if: github.event_name ==
'pull_request'`, while `ci-ok` at `:1217` counts a skipped job as a pass. A dispatched run
therefore goes green having skipped the protected-file guard -- a manufactured green. It
also loses the changed-files short circuit at `:231` and runs every heavy lane.
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
THROTTLE = Path.home() / ".claude" / "state" / "pr-reactor.last"
BOARD = Path.home() / ".claude" / "ESTATE_BOARD.jsonl"
REPO_DIR = Path("/Users/chidionyema/Documents/code/prospector")

# A verdict whose repair belongs to something else. The value is what to say when that
# something else turns out not to have fired, so the alert names the owner rather than the
# symptom -- whoever reads it should go and look at the owner, not re-derive the diagnosis.
OWNED = {
    "NO RUN":        "pr-keeper.yml should have dispatched CI (it has no schedule:, so it "
                     "only fires on a PR event or when main's CI goes green)",
    "CANCELLED":     "pr-keeper.yml re-runs a cancelled run (same trigger gap)",
    "GHOST ONLY":    "approve-parked-runs.yml approves parked runs every 10 minutes",
    "RUNNER KILLED": "nothing owns a killed runner; ci-fleet-keeper.yml replaces the machine "
                     "but nobody re-runs the build it took down",
    "MERGE UNKNOWN": "GitHub recomputes mergeability by itself; this long means it has not",
}
NEEDS_A_PERSON = {"REAL FAIL", "CONFLICT"}
NOTHING_TO_DO = {"GREEN", "IN PROGRESS"}

# How long a state may sit before someone hears about it. Long enough that a working owner
# (approve-parked-runs is on a 10-minute cron) always beats the watchdog to it; short enough
# that "close loops asap" means something. It is also the re-alert window for a red pull
# request nobody has touched, and the window in which another session's board row counts.
GRACE_S = 45 * 60
# Do not run the full triage more often than this. It costs 11.6s of GitHub calls (measured
# 2026-08-21) and the answer cannot change faster than CI does.
MIN_INTERVAL_S = 8 * 60


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


def prune(state: dict, now: float, keep_s: float = 14 * 86400) -> dict:
    """A merged pull request never appears again, so its key would sit here forever. Bound
    the file rather than letting a robot that runs every few minutes grow one without end."""
    return {k: v for k, v in state.items()
            if now - float((v or {}).get("first_seen") or now) < keep_s}


def board_ts(pr_number: int, rows: "list[dict]") -> float:
    """When did any session last raise this pull request on the estate board?

    A session that has already posted "PR #533 is RED, I am fixing it" has closed the loop a
    row of mine would only repeat. This is the peer-loop fence's rule applied to a robot that
    would otherwise be the loudest voice on the channel.
    """
    latest = 0.0
    want = ("#%d" % pr_number, "pr %d" % pr_number)
    for r in rows:
        t = (r.get("text") or "").lower()
        if any(w in t for w in want):
            try:
                ts = float(r.get("ts") or 0)
            except Exception:
                continue
            latest = max(latest, ts)
    return latest


def read_board(path: Path = BOARD, limit: int = 400) -> "list[dict]":
    rows = []
    try:
        for line in path.read_text(errors="replace").splitlines()[-limit:]:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue      # one unparseable row must not blind the whole check
    except Exception:
        pass
    return rows


def key_for(pr: dict) -> str:
    """A state is a pull request at a commit with a verdict. Any of the three changing is a
    new state deserving a fresh reaction -- especially the commit, because a new commit is
    the author answering the last alert."""
    return "%s@%s:%s" % (pr.get("pr"), (pr.get("sha") or "")[:12], pr.get("verdict"))


# ---------------------------------------------------------------- the decision (pure)

def _first_alert(p: dict, now: float, why: str) -> "tuple[str, str]":
    """The first time a pull request needs a person, ask whether one already knows."""
    bts = float(p.get("board_ts") or 0)
    if bts and now - bts < GRACE_S:
        # Do not add a second row. But start the clock at THEIR row, so if the session that
        # claimed it goes quiet, the next cycle still closes the loop.
        return "defer", "a session raised this %d minutes ago; deferring to them" % int(
            (now - bts) // 60)
    return "alert", why


def plan(prs: "list[dict]", state: dict, now: float) -> "list[dict]":
    """What to do about each pull request. Pure: no network, no clock, no disk.

    Every decision lives here so the selftest grades the decision itself rather than a mock
    of the thing that carries it out.
    """
    out = []
    for p in prs:
        v, k = p.get("verdict"), key_for(p)
        seen = state.get(k) or {}
        alerted_at = float(seen.get("alerted_at") or 0)
        first_seen = float(seen.get("first_seen") or now)
        age = now - first_seen

        if v in NOTHING_TO_DO:
            act, why = "none", "moving on its own"

        elif v in OWNED:
            # Someone else's repair. Leave it alone until it is provably not happening.
            if alerted_at:
                act, why = "none", "already escalated"
            elif age < GRACE_S:
                act, why = "watch", "owned elsewhere; %d of %d minutes into the grace window" % (
                    int(age // 60), int(GRACE_S // 60))
            else:
                act, why = _first_alert(p, now, "still %s after %d minutes -- %s" % (
                    v, int(age // 60), OWNED[v]))

        elif v == "DRAFT":
            # Green and drafted is a loop nobody holds: CI has nothing left to say and the
            # pull request still cannot merge. pr-keeper skips drafts on purpose. It is not
            # a failure, so it never re-runs; it is a nudge, once per commit.
            act, why = ("none", "already said") if alerted_at else _first_alert(
                p, now, "green but drafted; only the author can mark it ready")

        elif v in NEEDS_A_PERSON:
            if not alerted_at:
                act, why = _first_alert(p, now, p.get("detail") or v)
            elif now - alerted_at >= GRACE_S:
                act, why = "alert", "STILL %s after %d minutes: %s" % (
                    v, int((now - alerted_at) // 60), p.get("detail") or "")
            else:
                act, why = "none", "already alerted"

        else:
            # An unknown verdict is not a silence. A verdict added to pr_triage must surface
            # here rather than being dropped because this table has not caught up.
            act, why = _first_alert(
                p, now, "unrecognised verdict %r -- pr-reactor needs a rule for it" % v) \
                if not alerted_at else ("none", "already alerted")

        out.append({"pr": p.get("pr"), "branch": p.get("branch") or "", "verdict": v,
                    "sha": p.get("sha"), "run": p.get("run"), "key": k,
                    "action": act, "why": why, "board_ts": p.get("board_ts") or 0})
    return out


def apply_plan(planned: "list[dict]", state: dict, now: float, alert) -> "list[dict]":
    """Carry out a plan. `alert` is injected so the selftest never touches the board. A step
    that raises is recorded and does NOT stop the rest -- one unreachable pull request must
    not silence every other."""
    done = []
    for item in planned:
        k, act = item["key"], item["action"]
        rec = dict(state.get(k) or {})
        rec.setdefault("first_seen", now)
        try:
            if act == "defer":
                # Their row is the alert. Inheriting its timestamp is what makes the
                # escalation fire on the ORIGINAL discovery rather than on my noticing.
                rec["alerted_at"] = float(item.get("board_ts") or now)
                item["result"] = "deferred to an existing board row"
            elif act == "alert":
                alert(item)
                rec["alerted_at"] = now
                item["result"] = "alerted"
            else:
                item["result"] = act
        except Exception as exc:
            item["result"] = "ERROR: %s" % exc
        state[k] = rec
        done.append(item)
    return done


# ---------------------------------------------------------------- the world

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
    sha = {}
    try:
        g = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", "100",
                            "--json", "number,headRefOid"], cwd=str(REPO_DIR),
                           capture_output=True, text=True, timeout=120)
        if g.returncode == 0 and g.stdout.strip():
            sha = {r["number"]: r["headRefOid"] for r in json.loads(g.stdout)}
    except Exception:
        pass      # no sha means the key degrades to (pr, verdict): quieter, never louder
    prs = data.get("prs") or []
    rows = read_board()
    for r in prs:
        r["sha"] = sha.get(r.get("pr"), "")
        r["board_ts"] = board_ts(int(r.get("pr") or 0), rows)
    return prs


def do_alert(item: dict) -> None:
    """Put it where every session already looks. The estate board is handed to each session
    at start-up, so ONE row reaches every agent -- the cheap half of LAW 10, and the half
    that does not add to the message traffic the founder already called too noisy."""
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


# ---------------------------------------------------------------- hook mode

def due(path: Path, now: float, interval: float = MIN_INTERVAL_S) -> bool:
    try:
        return now - float(path.read_text().strip()) >= interval
    except Exception:
        return True      # no mark, or an unreadable one, means it has never run: run it


def hook() -> int:
    """Stop-hook entry. Costs the session nothing: it stamps the throttle and detaches.

    Deliberately NOT launchd. A reactor is only useful while agents are working, which is
    exactly when Stop fires, and it costs nothing at all when nobody is. The 11.6s triage
    must never sit in the path of a turn, so the child starts in its own session and this
    returns at once.
    """
    now = time.time()
    if not due(THROTTLE, now):
        return 0
    try:
        THROTTLE.parent.mkdir(parents=True, exist_ok=True)
        THROTTLE.write_text(str(now))
        log = Path.home() / ".claude" / "logs" / "pr-reactor.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            subprocess.Popen([sys.executable, os.path.abspath(__file__)],
                             stdout=fh, stderr=fh, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    except Exception:
        pass      # a reactor that cannot start must never take a turn down with it
    return 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    fails, total = [], [0]

    def ck(name, cond):
        total[0] += 1
        print("  %-64s %s" % (name[:64], "ok" if cond else "FAIL"))
        if not cond:
            fails.append(name)

    def pr(n, verdict, sha="aaaaaaaaaaaa", detail="d", branch="b"):
        return {"pr": n, "verdict": verdict, "sha": sha, "run": 1,
                "detail": detail, "branch": branch}

    T = 1_000_000.0
    noop = lambda i: None

    # --- what it reacts to ---------------------------------------------------
    p = plan([pr(1, "GREEN"), pr(2, "IN PROGRESS")], {}, T)
    ck("a green or in-flight pull request is left alone",
       [x["action"] for x in p] == ["none", "none"])

    p = plan([pr(8, "REAL FAIL"), pr(9, "CONFLICT")], {}, T)
    ck("a real failure and a conflict alert immediately",
       [x["action"] for x in p] == ["alert", "alert"])
    ck("the alert carries the CAUSE, not just the colour", p[0]["why"] == "d")

    # --- it repairs NOTHING: the whole point of the rewrite -------------------
    # Grade the parsed CODE, never the text. A previous version of this check grepped the
    # source for "pr merge", "workflow run" and so on -- and failed, because the list of
    # forbidden strings is itself in the source. That is the estate's own recorded trap:
    # a guard that greps source grades its comments, its help text and its own checker.
    import ast
    tree = ast.parse(Path(os.path.abspath(__file__)).read_text())
    shells, gh = 0, []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and getattr(node.func.value, "id", "") == "subprocess"
                and node.func.attr in ("run", "Popen", "call", "check_output", "check_call")):
            shells += 1
            if node.args and isinstance(node.args[0], ast.List):
                lits = [e.value for e in node.args[0].elts if isinstance(e, ast.Constant)]
                if lits and lits[0] == "gh":
                    gh.append(lits)
    ck("it shells out in exactly the three places this file documents", shells == 3)
    ck("it makes at least one call to gh", len(gh) == 1)
    ck("and every gh call is a READ -- it can never merge, close, re-run or dispatch",
       all(c[1:3] == ["pr", "list"] for c in gh))
    every = list(OWNED) + list(NEEDS_A_PERSON) + list(NOTHING_TO_DO) + ["DRAFT", "??"]
    ck("no verdict anywhere is routed to a repair",
       set(x["action"] for x in plan([pr(n, v) for n, v in enumerate(every)], {}, T))
       <= {"none", "watch", "alert", "defer"})

    # --- the watchdog on the owners ------------------------------------------
    for v in OWNED:
        st = {key_for(pr(30, v)): {"first_seen": T}}
        ck("%s is left to its owner inside the grace window" % v,
           plan([pr(30, v)], st, T + GRACE_S - 60)[0]["action"] == "watch")
        ck("%s alerts once the owner has provably not fired" % v,
           plan([pr(30, v)], st, T + GRACE_S + 60)[0]["action"] == "alert")
    ck("the escalation names the OWNER, so nobody re-derives the diagnosis",
       "pr-keeper" in plan([pr(30, "NO RUN")], {key_for(pr(30, "NO RUN")): {"first_seen": T}},
                           T + GRACE_S + 60)[0]["why"])
    st = {key_for(pr(31, "NO RUN")): {"first_seen": T}}
    apply_plan(plan([pr(31, "NO RUN")], st, T + GRACE_S + 60), st, T + GRACE_S + 60, noop)
    ck("a watchdog escalation is not repeated",
       plan([pr(31, "NO RUN")], st, T + GRACE_S * 5)[0]["action"] == "none")
    ck("a pull request seen for the FIRST time is watched, not alerted",
       plan([pr(32, "CANCELLED")], {}, T)[0]["action"] == "watch")

    # --- once, and only once -------------------------------------------------
    st = {}
    apply_plan(plan([pr(8, "REAL FAIL")], st, T), st, T, noop)
    ck("the same failure at the same commit does not alert twice",
       plan([pr(8, "REAL FAIL")], st, T + 60)[0]["action"] == "none")
    ck("a NEW commit on the same pull request alerts again",
       plan([pr(8, "REAL FAIL", sha="bbbbbbbbbbbb")], st, T + 60)[0]["action"] == "alert")
    ck("the same commit reaching a NEW verdict alerts again",
       plan([pr(8, "CONFLICT")], st, T + 60)[0]["action"] == "alert")
    ck("a pull request still red after the window says so once more",
       plan([pr(8, "REAL FAIL")], st, T + GRACE_S + 1)[0]["action"] == "alert")
    ck("and not one minute before that window",
       plan([pr(8, "REAL FAIL")], st, T + GRACE_S - 60)[0]["action"] == "none")

    # --- drafts and unknown verdicts -----------------------------------------
    st = {}
    p = plan([pr(12, "DRAFT")], st, T)
    ck("a green drafted pull request is nudged", p[0]["action"] == "alert")
    apply_plan(p, st, T, noop)
    ck("the draft nudge is not repeated",
       plan([pr(12, "DRAFT")], st, T + GRACE_S * 3)[0]["action"] == "none")
    p = plan([pr(13, "SOMETHING NEW")], {}, T)
    ck("a verdict this table does not know alerts rather than being dropped",
       p[0]["action"] == "alert" and "unrecognised" in p[0]["why"])

    # --- deferring to a session that already said it -------------------------
    st = {}
    recent = pr(20, "REAL FAIL"); recent["board_ts"] = T - 600
    pl = plan([recent], st, T)
    ck("a failure a session already raised gets no second board row",
       pl[0]["action"] == "defer")
    apply_plan(pl, st, T, noop)
    ck("deferring inherits THEIR timestamp, not mine",
       st[pl[0]["key"]]["alerted_at"] == T - 600)
    ck("and if they go quiet, the escalation still closes the loop",
       plan([recent], st, T + GRACE_S - 500)[0]["action"] == "alert")
    stale = pr(21, "REAL FAIL"); stale["board_ts"] = T - GRACE_S - 1
    ck("an OLD board row does not suppress a fresh alert",
       plan([stale], {}, T)[0]["action"] == "alert")
    watched = pr(23, "NO RUN"); watched["board_ts"] = T - 600
    ck("board deference also covers a watchdog escalation",
       plan([watched], {key_for(watched): {"first_seen": T - GRACE_S - 60}}, T)[0]["action"]
       == "defer")

    rows = [{"text": "PR #533 is RED on three python failures", "ts": "500"},
            {"text": "unrelated finding about #999", "ts": "700"},
            {"text": "later note on pr 533 as well", "ts": "900"}]
    ck("the board reader finds the newest mention of a pull request",
       board_ts(533, rows) == 900.0)
    ck("and does not match a different pull request", board_ts(534, rows) == 0.0)

    # --- failure modes -------------------------------------------------------
    st = {}
    def boom(i):
        raise RuntimeError("the board is gone")
    done = apply_plan(plan([pr(14, "REAL FAIL"), pr(15, "REAL FAIL", sha="cccccccccccc")],
                           st, T), st, T, boom)
    ck("an alert that throws is recorded and the next one still runs",
       len(done) == 2 and all(x["result"].startswith("ERROR") for x in done))
    ck("a failed alert is not recorded as delivered",
       all(not st[x["key"]].get("alerted_at") for x in done))
    ck("a pull request with no branch or detail does not crash the plan",
       plan([{"pr": 40, "verdict": "REAL FAIL"}], {}, T)[0]["action"] == "alert")

    with tempfile.TemporaryDirectory() as d:
        b = Path(d) / "b.jsonl"
        b.write_text('{"text":"#7 is red","ts":"1"}\nNOT JSON\n{"text":"#8","ts":"2"}\n')
        ck("one unparseable board row does not blind the check", len(read_board(b)) == 2)
        ck("a missing board is not fatal", read_board(Path(d) / "nope") == [])
        sp = Path(d) / "s.json"
        save_state(sp, {"a": {"first_seen": 1}})
        ck("state survives a round trip", load_state(sp) == {"a": {"first_seen": 1}})
        sp.write_text("{ not json")
        ck("a corrupt state file is not fatal", load_state(sp) == {})
        ck("a missing state file is not fatal", load_state(Path(d) / "nope.json") == {})

        # --- the throttle, which is what keeps it off the critical path ------
        m = Path(d) / "last"
        ck("with no mark at all it is due", due(m, T) is True)
        m.write_text(str(T))
        ck("it is not due again immediately", due(m, T + 60) is False)
        ck("it is due again after the interval", due(m, T + MIN_INTERVAL_S + 1) is True)
        m.write_text("not a number")
        ck("an unreadable throttle mark means run, never stay silent", due(m, T) is True)

    ck("state is pruned so a robot does not grow a file forever",
       prune({"old": {"first_seen": T - 30 * 86400}, "new": {"first_seen": T}}, T)
       == {"new": {"first_seen": T}})

    print("\n%d checks, %d failed" % (total[0], len(fails)))
    return 1 if fails else 0


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="say what it would do and change nothing")
    ap.add_argument("--hook", action="store_true",
                    help="Stop-hook mode: stamp the throttle, detach, return at once")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.hook:
        try:
            sys.stdin.read()      # the hook payload; nothing here needs it
        except Exception:
            pass
        return hook()

    state = load_state(STATE)
    now = time.time()
    try:
        prs = read_prs()
    except Exception as exc:
        # A reactor that cannot see is worse than one that is not running, because it looks
        # like "nothing is wrong". Say so loudly and exit non-zero.
        print("%s pr-reactor CANNOT SEE: %s" % (time.strftime("%H:%M"), exc), file=sys.stderr)
        return 2

    planned = plan(prs, state, now)
    print("%s -- %d open" % (time.strftime("%Y-%m-%d %H:%M"), len(planned)))
    for i in planned:
        print("  #%-4s %-14s %-32s %s: %s" % (i["pr"], i["verdict"], i["branch"][:32],
                                              i["action"].upper(), i["why"][:80]))
    if a.dry_run:
        print("(dry run: nothing was changed)")
        return 0

    done = apply_plan(planned, state, now, do_alert)
    save_state(STATE, prune(state, now))
    print("  %d alert(s) raised" % sum(1 for d in done if d["action"] == "alert"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
