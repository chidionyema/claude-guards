#!/usr/bin/env python3
"""Certify every agent in the estate against the capabilities it claims.

An agent's claims live in its own repository as REQUIREMENTS.jsonl: one JSON
object per line, each with a `statement` a person can read and an
`acceptance_cmd` a machine can run. A claim is true when its command exits 0.
No agent, and no session, can close a row by saying it is closed.

This runs every row for every registered agent, grades the result, appends the
run to a history file so a score can be compared with last week's, and messages
the founder only when a claim changes state. Green is reported once a day so
silence never has to mean "nobody checked".

Registry: agents.json, next to this file.
History:  ~/.claude/agent-cert/history.jsonl   (one line per agent per run)
Status:   ~/.claude/agent-cert/status.json     (what the founder board reads)

Why this exists next to hermes-v2's own bin/check-requirements.py rather than
replacing it: a repository's CI gate must not depend on a file outside that
repository, or the gate goes red the day the estate is checked out somewhere
else. That one runs inside hermes-v2's CI against hermes-v2. This one runs
across every agent and owns the history, the grade and the delivery. Same
contract, two targets.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "agents.json")
STATE_DIR = os.path.expanduser("~/.claude/agent-cert")
HISTORY = os.path.join(STATE_DIR, "history.jsonl")
STATUS = os.path.join(STATE_DIR, "status.json")

# A row gets the same ceiling hermes-v2 settled on. 25s was too tight there:
# one row shells out to a provider and took 9.1s on a good run, so a slow day
# turned a pass into a timeout and the score moved on its own.
ROW_TIMEOUT_S = 120

# Green goes out once a day. Alert-on-failure alone teaches the founder that
# silence means nothing was checked, and silence is also what a dead checker
# sounds like.
GREEN_EVERY_S = 24 * 3600


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_registry() -> list[dict]:
    with open(REGISTRY) as f:
        return json.load(f)["agents"]


def run_agent(agent: dict, only: str | None = None) -> dict:
    """Run every acceptance command this agent claims. Returns its scorecard."""
    home = os.path.expanduser(agent["home"])
    ledger = os.path.join(home, agent.get("ledger", "REQUIREMENTS.jsonl"))
    card = {"agent": agent["name"], "home": home, "at": now(),
            "rows": {}, "passed": 0, "failed": 0, "blocked": 0, "timed_out": 0,
            "error": None}

    if not os.path.exists(ledger):
        card["error"] = f"no claim ledger at {ledger}"
        return card

    # The agent's own home variable, plus a generic one, so a row can be written
    # either way and a new agent needs no change here.
    env = {**os.environ, "AGENT_HOME": home}
    if agent.get("home_env"):
        env[agent["home_env"]] = home
    for k, v in agent.get("env", {}).items():
        env[k] = os.path.expanduser(v)

    with open(ledger) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    for row in rows:
        if only and only not in (row.get("phase"), row.get("section"), row["id"]):
            continue
        try:
            proc = subprocess.run(["bash", "-c", row["acceptance_cmd"]],
                                  capture_output=True, timeout=ROW_TIMEOUT_S,
                                  env=env, cwd=home)
            rc = proc.returncode
            detail = (proc.stdout or proc.stderr).decode("utf-8", "replace").strip()
        except subprocess.TimeoutExpired:
            rc, detail = 124, f"no result in {ROW_TIMEOUT_S}s"
            card["timed_out"] += 1

        if rc == 0:
            state = "pass"
            card["passed"] += 1
        elif row.get("blocked_reason"):
            # Blocked is waiting on a founder decision, not on work. It is kept
            # out of the grade so it cannot hide inside a failure count, and it
            # is never alerted on.
            state = "blocked"
            card["blocked"] += 1
        else:
            state = "fail"
            card["failed"] += 1

        card["rows"][row["id"]] = {
            "state": state,
            "statement": row.get("statement", ""),
            "phase": row.get("phase"),
            "detail": detail[-400:],
            "blocked_reason": row.get("blocked_reason"),
        }

    graded = card["passed"] + card["failed"]
    card["graded"] = graded
    card["score"] = round(100.0 * card["passed"] / graded, 1) if graded else None
    return card


def previous(agent_name: str) -> dict | None:
    """The last recorded run for this agent, or None if it has never run."""
    if not os.path.exists(HISTORY):
        return None
    last = None
    with open(HISTORY) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("agent") == agent_name:
                last = rec
    return last


def transitions(card: dict, prev: dict | None) -> dict:
    """Which claims changed state since the last run. This is what gets sent."""
    if not prev:
        return {"first_run": True, "broke": [], "fixed": []}
    was = {rid: r["state"] for rid, r in prev.get("rows", {}).items()}
    broke, fixed = [], []
    for rid, r in card["rows"].items():
        before, after = was.get(rid), r["state"]
        if before == after or before is None:
            continue
        if after == "fail":
            broke.append((rid, r["statement"]))
        elif after == "pass" and before == "fail":
            fixed.append((rid, r["statement"]))
    return {"first_run": False, "broke": broke, "fixed": fixed}


def render(card: dict, trans: dict) -> str:
    name = card["agent"]
    if card["error"]:
        return f"{name}: cannot be certified. {card['error']}"
    score = "n/a" if card["score"] is None else f"{card['score']}%"
    head = (f"{name}: {card['passed']}/{card['graded']} claims proven ({score})"
            f"{', ' + str(card['blocked']) + ' blocked on you' if card['blocked'] else ''}")
    lines = [head]
    for rid, st in trans["broke"]:
        lines.append(f"  BROKE  {rid} {st}")
    for rid, st in trans["fixed"]:
        lines.append(f"  FIXED  {rid} {st}")
    return "\n".join(lines)


def unproven(card: dict) -> list[str]:
    return [f"{rid} {r['statement']}" for rid, r in sorted(card["rows"].items())
            if r["state"] == "fail"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent", help="certify one agent by name instead of all")
    ap.add_argument("--only", help="one phase, section or requirement id")
    ap.add_argument("--quiet", action="store_true",
                    help="no Telegram; used when a person is watching the output")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any claim is unproven; for a CI gate")
    ap.add_argument("--json", action="store_true", help="print the scorecards as JSON")
    args = ap.parse_args()

    agents = [a for a in load_registry()
              if not args.agent or a["name"] == args.agent]
    if not agents:
        print(f"no agent named {args.agent} in {REGISTRY}", file=sys.stderr)
        return 2

    os.makedirs(STATE_DIR, exist_ok=True)
    cards, messages = [], []
    for agent in agents:
        card = run_agent(agent, args.only)
        prev = previous(card["agent"])
        trans = transitions(card, prev)
        cards.append(card)

        # History first, so a crash in delivery never loses the measurement.
        # A filtered run is recorded but not compared against, because a subset
        # would read as every other claim having vanished.
        if not args.only:
            with open(HISTORY, "a") as f:
                f.write(json.dumps(card) + "\n")

        text = render(card, trans)
        print(text)
        for line in unproven(card):
            print(f"  unproven: {line}")
        if trans["broke"] or trans["first_run"] or card["error"]:
            messages.append(text)

    status = {
        "last_run_at": now(),
        "last_run_epoch": int(time.time()),
        "agents": {c["agent"]: {"passed": c["passed"], "graded": c["graded"],
                                "blocked": c["blocked"], "score": c["score"],
                                "error": c["error"],
                                "unproven": unproven(c)} for c in cards},
    }
    if not args.only:
        with open(STATUS, "w") as f:
            json.dump(status, f, indent=1, sort_keys=True)

    if args.json:
        print(json.dumps(cards, indent=1, sort_keys=True))

    if not args.quiet:
        deliver(cards, messages)

    if args.strict and any(c["failed"] or c["error"] for c in cards):
        return 1
    return 0


def deliver(cards: list[dict], messages: list[str]) -> None:
    """Message the founder on a change, and once a day when nothing changed."""
    sys.path.insert(0, HERE)
    try:
        import estate_alert
    except Exception as exc:                       # never let alerting break the run
        print(f"[agent-cert] cannot load estate_alert: {exc!r}", file=sys.stderr)
        return

    if messages:
        body = "Agent certification changed\n\n" + "\n\n".join(messages)
        ok = estate_alert.send_operator_alert(body, debounce_key="agent-cert-change",
                                              debounce_s=600)
        print(f"[agent-cert] change alert delivered={ok}")
        return

    stamp = os.path.join(STATE_DIR, "last-green.txt")
    try:
        last = float(open(stamp).read().strip())
    except (OSError, ValueError):
        last = 0.0
    if time.time() - last < GREEN_EVERY_S:
        return
    lines = [f"{c['agent']}: {c['passed']}/{c['graded']} claims proven" for c in cards]
    ok = estate_alert.send_operator_alert(
        "Agent certification, no change\n\n" + "\n".join(lines),
        debounce_key="agent-cert-green", debounce_s=GREEN_EVERY_S - 60)
    print(f"[agent-cert] daily green delivered={ok}")
    if ok:
        with open(stamp, "w") as f:
            f.write(str(time.time()))


if __name__ == "__main__":
    sys.exit(main())
