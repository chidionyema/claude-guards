#!/usr/bin/env python3
"""The board, as code. crew#306 (founder, 2026-08-26): "You never say 'keep moving' again.
The system moves them."

One source of truth: open issues in the crew repo. An item is CLAIMED when its newest
CLAIM/RELEASE comment is a CLAIM, or it has an assignee. Everything else is unclaimed and
the oldest (lowest number) is next. Meta issues (the board itself, the broadcast board) are
never work items.

Every gh call fails open: a board that cannot be read returns None, never an empty list, so
a caller can tell BLIND from "nothing left" (memory: an-audit-that-crashes-reports-nothing).

A selftest can point ESTATE_BOARD_FIXTURE at a JSON file of issues; then nothing shells out
and nothing is posted -- comments land in <fixture>.posted.jsonl instead.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


# launchd jobs start with PATH=/usr/bin:/bin, where gh is not. Standard install
# dirs, not machine names (LAW 46). Incident: crew#306 --scan printed BLIND every 5 min.
_GH_DIRS = ("/usr/local/bin", "/opt/homebrew/bin")


def gh_bin() -> str:
    found = shutil.which("gh")
    if found:
        return found
    for d in _GH_DIRS:
        cand = os.path.join(d, "gh")
        if os.access(cand, os.X_OK):
            return cand
    return "gh"

REPO = os.environ.get("ESTATE_BOARD_REPO", "chidionyema/crew")
META_ISSUES = {102, 133}          # ESTATE BOARD, THE BOARD -- lists of work, not work
META_LABELS = {"board", "meta", "epic"}
CLAIM = "CLAIM "
RELEASE = "RELEASE "
BLOCKED = "BLOCKED:"
VALID = "VALID:"
INVALID = "INVALID:"
LEDGER = Path(os.path.expanduser("~/.claude/state/ledger.jsonl"))


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ledger(entry: dict) -> None:
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        entry.setdefault("ts", utc())
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _fixture() -> Path | None:
    p = os.environ.get("ESTATE_BOARD_FIXTURE")
    return Path(p) if p else None


def open_issues() -> list[dict] | None:
    """[{number, title, labels:[str], assignees:[str], comments:[{body, created_at}]}] or None."""
    fx = _fixture()
    if fx:
        try:
            return json.loads(fx.read_text())
        except Exception:
            return None
    try:
        out = subprocess.run(
            [gh_bin(), "issue", "list", "-R", REPO, "--state", "open", "--limit", "200",
             "--json", "number,title,labels,assignees,comments,createdAt"],
            capture_output=True, text=True, timeout=40)
        if out.returncode != 0:
            return None
        rows = json.loads(out.stdout)
    except Exception:
        return None
    norm = []
    for r in rows:
        norm.append({
            "number": r["number"], "title": r.get("title", ""),
            "labels": [l.get("name", "") for l in r.get("labels", [])],
            "assignees": [a.get("login", "") for a in r.get("assignees", [])],
            "created_at": r.get("createdAt", ""),
            "comments": [{"body": c.get("body", ""), "created_at": c.get("createdAt", "")}
                         for c in r.get("comments", [])],
        })
    return norm


def is_work(issue: dict) -> bool:
    if issue["number"] in META_ISSUES:
        return False
    return not (set(l.lower() for l in issue.get("labels", [])) & META_LABELS)


def claimed(issue: dict) -> bool:
    if issue.get("assignees"):
        return True
    state = False
    for c in issue.get("comments", []):
        b = (c.get("body") or "").lstrip()
        if b.startswith(CLAIM):
            state = True
        elif b.startswith(RELEASE):
            state = False
    return state


def unclaimed(issues: list[dict]) -> list[dict]:
    return sorted((i for i in issues if is_work(i) and not claimed(i)), key=lambda i: i["number"])


def oldest_unclaimed() -> dict | None | str:
    """A work item, None when the board is empty, or "BLIND" when it cannot be read."""
    issues = open_issues()
    if issues is None:
        return "BLIND"
    items = unclaimed(issues)
    return items[0] if items else None


def comment(number: int, body: str) -> bool:
    fx = _fixture()
    if fx:
        try:
            with open(str(fx) + ".posted.jsonl", "a") as fh:
                fh.write(json.dumps({"number": number, "body": body}) + "\n")
            return True
        except Exception:
            return False
    try:
        r = subprocess.run([gh_bin(), "issue", "comment", str(number), "-R", REPO, "--body", body],
                           capture_output=True, text=True, timeout=40)
        return r.returncode == 0
    except Exception:
        return False


def claim(number: int, session: str, lane: str, why: str) -> bool:
    return comment(number, f"{CLAIM}{utc()} session {session[:8]} lane {lane}: {why}")


def release(number: int, session: str, why: str) -> bool:
    return comment(number, f"{RELEASE}{utc()} session {session[:8]}: {why}")


def goal_number(goal: str) -> int | None:
    import re
    m = re.search(r"crew#(\d+)", goal or "")
    return int(m.group(1)) if m else None


# ---- transcript helpers shared by the Stop hooks -------------------------------------

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def last_texts(transcript: str) -> tuple[str, str]:
    """(last user text, last assistant text). Missing -> ""."""
    user = assistant = ""
    try:
        with open(transcript, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                msg = row.get("message") or {}
                t = row.get("type")
                if t == "user" and not row.get("toolUseResult"):
                    txt = _text_of(msg.get("content"))
                    if txt.strip() and not txt.lstrip().startswith("<"):
                        user = txt
                elif t == "assistant":
                    txt = _text_of(msg.get("content"))
                    if txt.strip():
                        assistant = txt
    except Exception:
        pass
    return user, assistant


def founder_word(user_text: str) -> str:
    """'STOP', 'RELEASE', 'BLOCKED' or ''. Exact words, so 'stop hook feedback' never matches."""
    t = user_text.strip()
    if t in ("STOP", "STOP.", "RELEASE", "RELEASE."):
        return t.rstrip(".")
    if t.startswith(BLOCKED):
        return "BLOCKED"
    return ""


BLOCKED_FIELDS = ("Tried:", "Error:", "Need:", "Who:")


def blocked_missing(text: str) -> list[str]:
    """The fields a BLOCKED: reply lacks. Empty list means it is a validated escape."""
    return [f for f in BLOCKED_FIELDS if f not in text]


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import tempfile
        ok = True
        def ck(label, cond):
            global ok
            ok = ok and bool(cond)
            print(("PASS " if cond else "FAIL ") + label)
        fx = [
            {"number": 133, "title": "THE BOARD", "labels": [], "assignees": [], "comments": []},
            {"number": 12, "title": "claimed", "labels": [], "assignees": [],
             "comments": [{"body": "CLAIM 2026-08-26T00:00:00Z session abc: x"}]},
            {"number": 30, "title": "released", "labels": [], "assignees": [],
             "comments": [{"body": "CLAIM 2026-08-26T00:00:00Z session abc: x"},
                          {"body": "RELEASE 2026-08-26T01:00:00Z session abc: timeout"}]},
            {"number": 20, "title": "assigned", "labels": [], "assignees": ["someone"], "comments": []},
            {"number": 40, "title": "epic", "labels": ["epic"], "assignees": [], "comments": []},
            {"number": 50, "title": "fresh", "labels": [], "assignees": [], "comments": []},
        ]
        d = tempfile.mkdtemp()
        p = Path(d) / "fx.json"; p.write_text(json.dumps(fx))
        os.environ["ESTATE_BOARD_FIXTURE"] = str(p)
        items = [i["number"] for i in unclaimed(open_issues())]
        ck("meta, claimed, assigned and epic are skipped; released and fresh remain, oldest first",
           items == [30, 50])
        ck("oldest unclaimed is #30", oldest_unclaimed()["number"] == 30)
        p.write_text("not json")
        ck("an unreadable board is BLIND, never empty", oldest_unclaimed() == "BLIND")
        p.write_text("[]")
        ck("an empty board is None", oldest_unclaimed() is None)
        ck("claim posts to the fixture, not gh", claim(50, "sess1234abcd", "code", "why")
           and "CLAIM " in open(str(p) + ".posted.jsonl").read())
        ck("founder STOP is a word", founder_word("STOP") == "STOP")
        ck("'Stop hook feedback' is not", founder_word("Stop hook feedback: x") == "")
        ck("a full BLOCKED reply has no missing field",
           blocked_missing("BLOCKED: x\nTried: a\nError: b\nNeed: c\nWho: d") == [])
        ck("a bare BLOCKED reply lists all four", blocked_missing("BLOCKED: no") == list(BLOCKED_FIELDS))
        ck("goal_number reads crew#N", goal_number("crew#306: ship it") == 306)
        print("PASS estate_board" if ok else "FAIL estate_board")
        sys.exit(0 if ok else 1)
