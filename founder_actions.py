#!/usr/bin/env python3
"""Every thing only the founder can authorise, in one place, closing itself when it is done.

THE PROBLEM THIS EXISTS FOR. Authorisation in this estate is retail. An agent works, hits a
wall only the founder can clear, and spends a reply telling him about that one wall. The next
agent hits a different wall and spends another reply. Measured on 2026-08-23 in a single
session: three separate founder-only items surfaced in three separate turns -- the encrypted
secret store, escrowing the age key off this laptop, and the Fly invoice. Each cost a round
trip, none of them was visible anywhere, and none of them was visible NEXT to the others.

That is the actual blocker, and it is not any one guard. Work stalls at an authorisation step,
the stall is reported as prose to a person who has to hold it in his head, and the estate has
no idea how many such steps are outstanding. LAW 31 says the founder does not run commands, so
a design that hands him one is a defect. Where that is unavoidable -- proving identity, moving
money, an irreversible act -- the least we can do is batch them, so one visit clears all of
them instead of one.

WHAT MAKES THIS DIFFERENT FROM A TODO LIST. An item closes when a command says the world
changed, never when an agent asserts it did. `done_when` is a shell command; exit 0 means the
thing happened and the item disappears on the next sweep with nobody remembering to close it.

An item whose truth NO command can establish is allowed, and it is the honest case for
something like "back the key up somewhere off this laptop". It carries `done_when: null`, it
is reported as UNVERIFIABLE rather than open or done, and it never grades green by accident.
An allow-list with a silent miss case dropped 10 criticals in 18 hours on this estate.

    python3 founder_actions.py                 # what is outstanding, and what it is blocking
    python3 founder_actions.py --json          # for the estate board
    python3 founder_actions.py --sweep         # run every done_when, retire what has happened
    python3 founder_actions.py --add-file f    # append one item from a JSON file
    python3 founder_actions.py --selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
REGISTER = os.environ.get(
    "FOUNDER_ACTIONS_FILE", os.path.join(HOME, ".claude", "state", "founder-actions.jsonl")
)
FIELDS = ("id", "what", "why_founder", "unblocks", "done_when", "opened", "source")

OPEN, DONE, UNVERIFIABLE = "open", "done", "unverifiable"


def _load() -> list[dict]:
    """Read the register. A malformed line is reported, never silently skipped."""
    if not os.path.exists(REGISTER):
        return []
    items, bad = [], 0
    with open(REGISTER, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
                items.append({"id": f"__malformed_line_{n}", "what": line[:120],
                              "why_founder": "this line of the register is not JSON",
                              "unblocks": "", "done_when": None, "opened": "", "source": ""})
    return items


def _save(items: list[dict]) -> None:
    tmp = REGISTER + ".tmp"
    os.makedirs(os.path.dirname(REGISTER), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps({k: it.get(k) for k in FIELDS}, ensure_ascii=False) + "\n")
    os.replace(tmp, REGISTER)


def add(item: dict) -> str:
    """Append one item. An id that already exists is updated rather than duplicated."""
    missing = [f for f in ("id", "what", "why_founder") if not item.get(f)]
    if missing:
        raise ValueError("an item needs %s" % ", ".join(missing))
    item.setdefault("opened", dt.date.today().isoformat())
    item.setdefault("done_when", None)
    item.setdefault("unblocks", "")
    item.setdefault("source", "")
    items = _load()
    for i, existing in enumerate(items):
        if existing.get("id") == item["id"]:
            items[i] = {k: item.get(k, existing.get(k)) for k in FIELDS}
            _save(items)
            return "updated %s" % item["id"]
    items.append(item)
    _save(items)
    return "added %s" % item["id"]


def state_of(item: dict) -> tuple[str, str]:
    """(state, proof). A command decides, never an assertion."""
    cmd = item.get("done_when")
    if not cmd:
        return UNVERIFIABLE, "no command can establish this, so it stays visible until retired"
    try:
        p = subprocess.run(["/bin/bash", "-lc", cmd], capture_output=True,
                           text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return OPEN, "done_when timed out after 20s, so this is not a pass: %s" % cmd
    except Exception as exc:                              # noqa: BLE001 - a probe reports
        return OPEN, "done_when errored (%s), so this is not a pass" % type(exc).__name__
    return (DONE if p.returncode == 0 else OPEN), "%s -> exit %d" % (cmd, p.returncode)


def sweep(retire: bool = True) -> list[dict]:
    """Grade every item. Retiring drops the done ones out of the register for good."""
    graded = []
    for it in _load():
        st, proof = state_of(it)
        graded.append(dict(it, state=st, proof=proof))
    if retire:
        keep = [{k: g.get(k) for k in FIELDS} for g in graded if g["state"] != DONE]
        if len(keep) != len(graded):
            _save(keep)
    return graded


def report() -> dict:
    graded = sweep(retire=False)
    return {
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "register": REGISTER,
        # An absent register and an empty one produce the same empty lists, and reading them
        # the same way is how a board goes green on a file somebody deleted. The reader needs
        # to be able to tell the two apart, so say which this is.
        "register_exists": os.path.exists(REGISTER),
        "open": [g for g in graded if g["state"] == OPEN],
        "unverifiable": [g for g in graded if g["state"] == UNVERIFIABLE],
        "done": [g for g in graded if g["state"] == DONE],
    }


def selftest() -> int:
    """Two properties, not ten examples: a command decides, and a missing one never passes."""
    global REGISTER
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        REGISTER = os.path.join(tmp, "reg.jsonl")
        add({"id": "t-true", "what": "already true", "why_founder": "n/a", "done_when": "true"})
        add({"id": "t-false", "what": "not yet", "why_founder": "n/a", "done_when": "false"})
        add({"id": "t-none", "what": "unknowable", "why_founder": "n/a"})
        r = report()
        if [g["id"] for g in r["done"]] != ["t-true"]:
            fails.append("a done_when exiting 0 must read done, got %s" % r["done"])
        if [g["id"] for g in r["open"]] != ["t-false"]:
            fails.append("a done_when exiting non-zero must read open, got %s" % r["open"])
        if [g["id"] for g in r["unverifiable"]] != ["t-none"]:
            fails.append("a missing done_when must never read done, got %s" % r["unverifiable"])
        add({"id": "t-false", "what": "changed", "why_founder": "n/a", "done_when": "false"})
        if len([i for i in _load() if i["id"] == "t-false"]) != 1:
            fails.append("re-adding an id must update, not duplicate")
        sweep(retire=True)
        if any(i["id"] == "t-true" for i in _load()):
            fails.append("sweep must retire a done item out of the register")
        if not any(i["id"] == "t-none" for i in _load()):
            fails.append("sweep must keep an unverifiable item")
    for f in fails:
        print("FAIL %s" % f)
    print("selftest: %s" % ("PASS" if not fails else "%d FAILED" % len(fails)))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sweep", action="store_true", help="retire items whose done_when passes")
    ap.add_argument("--add-file", help="a JSON file holding one item, or a list of them")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.add_file:
        with open(a.add_file, encoding="utf-8") as fh:
            payload = json.load(fh)
        for item in (payload if isinstance(payload, list) else [payload]):
            print(add(item))
        return 0
    if a.sweep:
        graded = sweep(retire=True)
        for g in graded:
            print("%-9s %-26s %s" % (g["state"].upper(), g["id"], g["proof"]))
        return 0

    r = report()
    if a.json:
        print(json.dumps(r, indent=2))
        return 0
    n = len(r["open"]) + len(r["unverifiable"])
    if not n:
        print("nothing is waiting on the founder")
        return 0
    print("%d thing%s only the founder can clear" % (n, "" if n == 1 else "s"))
    for g in r["open"] + r["unverifiable"]:
        print("\n  [%s] %s" % (g["state"], g["what"]))
        print("      only him because: %s" % g["why_founder"])
        if g.get("unblocks"):
            print("      it releases:      %s" % g["unblocks"])
        if g.get("source"):
            print("      tracked at:       %s" % g["source"])
        print("      closes when:      %s" % g["proof"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
