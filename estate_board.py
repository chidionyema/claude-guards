#!/usr/bin/env python3
"""The board, as code. crew#306 (founder, 2026-08-26): "You never say 'keep moving' again.
The system moves them."

One source of truth: open issues in the crew repo. An item is CLAIMED when its newest
CLAIM/RELEASE comment is a CLAIM, or it has an assignee. Everything else is unclaimed and
the highest-ranked is next: finish-first (crew#527 CP2, founder 2026-08-27 "we have many
features half done"): fraction of checklist boxes ticked, then P0/P1, then founder-request,
then age; an issue whose `Blocked-on: #N` names an open issue ranks below every unblocked one. Meta issues (the board itself, the broadcast board) are
never work items.

Every gh call fails open: a board that cannot be read returns None, never an empty list, so
a caller can tell BLIND (exit 3, never argparse's 2) from "nothing left" (memory: an-audit-that-crashes-reports-nothing).

A selftest can point ESTATE_BOARD_FIXTURE at a JSON file of issues; then nothing shells out
and nothing is posted -- comments land in <fixture>.posted.jsonl instead.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from issue_dod import LEGACY_FOUNDER_BOX  # noqa: E402  (one copy of the line, never two)

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
            [gh_bin(), "issue", "list", "-R", REPO, "--state", "open", "--limit", "500",
             "--json", "number,title,labels,assignees,comments,createdAt,body"],
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
            "created_at": r.get("createdAt", ""), "body": r.get("body") or "",
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


def boxes(issue: dict) -> tuple[int, int]:
    b = issue.get("body") or ""
    return len(re.findall(r"- \[x\]", b, re.IGNORECASE)), len(re.findall(r"- \[ \]", b))


def awaiting_receipt(issue: dict) -> bool:
    """True when every unticked box is the legacy founder-receipt line and nothing else.

    Founder, 2026-08-28: "should be waiting on [me] unless its physical action [machines] cannot
    do" (R5). issue_dod.py stamped "Founder used it and confirmed" on every auto-opened issue, so
    a finished item and an untouched one both landed in `no_rule` and the nightly line could not
    tell them apart. On 2026-08-28 that hid three built-and-proved issues, one of them a P0.
    Matched against the exact literal imported from issue_dod, not against the words "founder" or
    "receipt": an English-word match would also catch crew#527's "after 7 days" receipt and
    crew#345's "zero founder interaction", both of which are ours to prove, and both of which a
    fuzzy filter did in fact misfile before this function existed."""
    un = re.findall(r"^\s*[-*] \[ \] (.*)$", issue.get("body") or "", re.M)
    return bool(un) and all(LEGACY_FOUNDER_BOX in u for u in un)


def blocked_on(issue: dict) -> set[int]:
    return {int(n) for n in re.findall(r"^Blocked-on:.*?#(\d+)", issue.get("body") or "", re.MULTILINE | re.IGNORECASE)}


def rank_key(issue: dict, open_numbers: set[int]) -> tuple:
    """Finish-first. Lower sorts first: unblocked, most of its boxes ticked, P0 before P1,
    founder-request, then oldest. An issue with no checklist ranks as 0 ticked. An all-ticked
    issue is not work at all (see is_work): it is a close-chore for the nightly closer (crew#526)."""
    t, u = boxes(issue)
    frac = t / (t + u) if t + u else 0.0
    labels = {l.lower() for l in issue.get("labels", [])}
    prio = 0 if "p0" in labels else 1 if "p1" in labels else 2
    blocked = bool(blocked_on(issue) & open_numbers)
    return (blocked, -frac, prio, "founder-request" not in labels, issue["number"])


def all_ticked(issue: dict) -> bool:
    t, u = boxes(issue)
    return t > 0 and u == 0


def unclaimed(issues: list[dict]) -> list[dict]:
    open_numbers = {i["number"] for i in issues}
    return sorted((i for i in issues if is_work(i) and not claimed(i) and not all_ticked(i)),
                  key=lambda i: rank_key(i, open_numbers))


def next_unclaimed() -> dict | None | str:
    """The top-ranked work item, None when the board is empty, or "BLIND" when it cannot be read."""
    issues = open_issues()
    if issues is None:
        return "BLIND"
    items = unclaimed(issues)
    return items[0] if items else None


# --- crew#527 CP3: the board assigns ------------------------------------------------------------
FEED = Path(os.environ.get("ESTATE_FEED") or os.path.expanduser("~/.estate/feed.md"))
ALIVE_HOURS = float(os.environ.get("ESTATE_BOARD_ALIVE_HOURS", "2"))
STALE_HOURS = float(os.environ.get("ESTATE_BOARD_STALE_HOURS", "24"))
_CLAIM_RE = re.compile(r"^CLAIM (\S+) session (\w{1,8})")
_FEED_RE = re.compile(r"^## (\S+) · session (\w{1,8}) · lane (\S+)", re.MULTILINE)


def _ts(s: str) -> float:
    import calendar
    return calendar.timegm(time.strptime(s[:16], "%Y-%m-%dT%H:%M"))


def claimed_by(issue: dict) -> tuple[str, str] | None:
    """(session, utc) of the claim in force, or None. The CLAIM body carries its own stamp."""
    state = None
    for c in issue.get("comments", []):
        b = (c.get("body") or "").lstrip()
        m = _CLAIM_RE.match(b)
        if m:
            state = (m.group(2), m.group(1))
        elif b.startswith(RELEASE):
            state = None
    return state


def alive_sessions(feed_text: str, now: float, hours: float = ALIVE_HOURS) -> dict[str, str]:
    """session -> lane for every session whose newest feed handoff is younger than `hours`."""
    latest: dict[str, tuple[float, str]] = {}
    for at, sess, lane in _FEED_RE.findall(feed_text):
        try:
            t = _ts(at)
        except ValueError:
            continue
        if sess not in latest or t > latest[sess][0]:
            latest[sess] = (t, lane)
    return {s: lane for s, (t, lane) in latest.items() if now - t <= hours * 3600}


def _last_boxes_seen(path: Path = LEDGER) -> dict[int, tuple[int, float]]:
    """item -> (ticked, since): the ticked count the board sees now and the FIRST `board seen`
    row of the unbroken run that has shown it. The board writes a row every turn, so the newest
    row is never 24h old (code-99 REWORK on claude-guards#166); the oldest row with the
    current count is the baseline that lets the stale-release fire."""
    seen: dict[int, tuple[int, float]] = {}
    try:
        for line in path.read_text().splitlines():
            e = json.loads(line)
            if e.get("guard") != "board" or e.get("event") != "seen":
                continue
            n, t, at = int(e["item"]), int(e["ticked"]), _ts(e["ts"])
            if n not in seen or seen[n][0] != t:
                seen[n] = (t, at)
    except (OSError, ValueError, KeyError):
        pass
    return seen


def assign(issues: list[dict], alive: dict[str, str], now: float, seen: dict[int, tuple[int, float]],
           post: bool = True) -> dict:
    """The board's turn. Returns {"released": [...], "assigned": [...], "held": {...}}.

    1. A claim older than STALE_HOURS whose ticked count has not moved since the board last
       saw it is released and re-ranked (the ledger row `board seen` is the baseline).
    2. Every alive session (a feed handoff in the last ALIVE_HOURS) holding no claim gets the
       top unclaimed item, one per session, in rank order. A session holding a claim keeps it:
       nobody starts a new feature while their half-done one is above it (crew#527 CP3)."""
    released, assigned, held = [], [], {}
    for i in issues:
        who = claimed_by(i)
        if not who or not is_work(i):
            continue
        sess, at = who
        t, _u = boxes(i)
        base = seen.get(i["number"])
        try:
            age = now - _ts(at)
        except ValueError:
            age = 0.0
        if base and age > STALE_HOURS * 3600 and now - base[1] > STALE_HOURS * 3600 and base[0] == t:
            if post:
                release(i["number"], "board", f"assignment {at} by {sess}: {STALE_HOURS:g}h with no box ticked, re-ranked")
                i["comments"] = [*i.get("comments", []), {"body": f"{RELEASE}{utc()} session board"}]
            released.append(i["number"])
            continue
        held.setdefault(sess, []).append(i["number"])
    if post:
        for i in issues:
            if is_work(i):
                t, _u = boxes(i)
                ledger({"guard": "board", "event": "seen", "item": i["number"], "ticked": t})
    queue = unclaimed(issues)
    for sess, lane in sorted(alive.items()):
        if sess in held or not queue:
            continue
        item = queue.pop(0)
        if post:
            claim(item["number"], sess, lane, "assigned by the board: top of the finish-first rank")
        assigned.append((sess, item["number"]))
    return {"released": released, "assigned": assigned, "held": held}


def assignment_for(session: str, issues: list[dict] | None = None) -> dict | None:
    """The open item this session holds a claim on, if any (auto-objective reads this first)."""
    issues = open_issues() if issues is None else issues
    for i in issues or []:
        who = claimed_by(i)
        if who and who[0] == session[:8] and is_work(i) and not all_ticked(i):
            return i
    return None


# crew#526 CP2 (founder 2026-08-27: "158 unclaimed open how come this never goes down"): nothing ever
# read a ticked checklist or a Closes-when line back. The nightly close turn does both, and every
# close carries the receipt (the command and its exit, or the ticked count and how long it stood).
CLOSES_WHEN = re.compile(r"^Closes-when:\s*`?([^`\n]+?)`?\s*$", re.M)
CLOSER_LOG = os.environ.get("ESTATE_CLOSER_LOG", "")
# LAW 21 (code-99 on cg#169): an issue body is anyone's text. The board runs exactly one shape of
# command, the datamap row probe; every other Closes-when line is refused, counted, never executed.
# crew#526 (09cd04a6, 2026-08-28): the first grammar was `--row [A-Za-z0-9_.-]+`, and no live row
# key can be spelled in it. Every key in science/verdicts.json carries `/` and most carry `*`
# (`mac/*state/pi-bridge-runs*`), so 0 of 60 rows were runnable, `by_rule["closes-when"]` was 0 on
# every turn, and crew#533 was refused for naming its own row. A key is dot-joined atoms joined by
# `/`: that accepts every real key (two of them carry `~`, and hidden segments like `.estate` are
# ordinary) and still cannot spell `..`, a space or a shell metacharacter -- a segment may open
# with one dot, never two, because the dot must be followed by an atom.
# The command runs through shlex.split with no shell, so `*` and `~` reach datamap.py literally.
_ROW_ATOM = r"[A-Za-z0-9_*~-]+"
_ROW_SEG = rf"\.?{_ROW_ATOM}(?:\.{_ROW_ATOM})*"
# `\Z`, not `$`: `$` also matches before a trailing newline, so `--row mac/data\n` would have
# been accepted (d5ae1960 on cg#188). Harmless with no shell, but the comment above claims a
# newline is refused and the pattern has to be what the comment says.
ALLOWED_CLOSES_WHEN = re.compile(rf"^python3 science/datamap\.py --row {_ROW_SEG}(?:/{_ROW_SEG})*\Z")
MAX_CLOSES_WHEN = 200  # a body is anyone's text; a row key is never this long


def closes_when(issue: dict) -> str | None:
    """The exact command whose exit 0 closes the issue, backticks stripped (code-99 on crew#531)."""
    m = CLOSES_WHEN.search(issue.get("body") or "")
    return m.group(1).strip() if m else None


def _run_closes_when(cmd: str, cwd: str) -> tuple[int, str]:
    import shlex
    try:
        r = subprocess.run(shlex.split(cmd), cwd=cwd, capture_output=True, text=True, timeout=300, check=False)
        return r.returncode, (r.stdout or r.stderr).strip()[-300:]
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return 3, f"could not run: {e}"[:300]


def close_issue(number: int, receipt: str) -> bool:
    fx = _fixture()
    if fx:
        try:
            with open(str(fx) + ".posted.jsonl", "a") as fh:
                fh.write(json.dumps({"number": number, "close": receipt}) + "\n")
            return True
        except OSError:
            return False
    try:
        r = subprocess.run([gh_bin(), "issue", "close", str(number), "-R", REPO, "--reason", "completed",
                            "--comment", receipt], capture_output=True, text=True, timeout=40, check=False)
        return r.returncode == 0
    except OSError:
        return False


def close_pass(issues: list[dict], now: float, seen: dict[int, tuple[int, float]], cwd: str,
               post: bool = True, run=_run_closes_when, stale_hours: float = STALE_HOURS) -> dict:
    """One close turn. Returns {closed: [(n, why)], ran: n, held: n, no_rule: n, refused: n}.
    - an issue with an allow-listed Closes-when line closes when that command exits 0;
    - a Closes-when line outside ALLOWED_CLOSES_WHEN is refused: counted, logged, never run;
    - an issue with every box ticked closes once the board has seen that count for stale_hours;
    - an issue whose only unticked box is the legacy founder receipt is counted
      separately (awaiting_receipt), because it is finished work, not unstarted work;
    - anything else is held, counted, never touched."""
    out = {"closed": [], "ran": 0, "held": 0, "no_rule": 0, "refused": 0, "awaiting_receipt": 0}
    for i in issues:
        n = i["number"]
        cmd = closes_when(i)
        if cmd and (len(cmd) > MAX_CLOSES_WHEN or not ALLOWED_CLOSES_WHEN.match(cmd)):
            out["refused"] += 1
            ledger({"guard": "board", "event": "refused", "item": n, "rule": "closes-when", "cmd": cmd[:120]})
            continue
        if cmd:
            out["ran"] += 1
            rc, tail = run(cmd, cwd)
            if rc == 0:
                why = f"CLOSED {utc()} by the board: `{cmd}` exit 0\n\n```\n{tail}\n```"
                if not post or close_issue(n, why):
                    out["closed"].append((n, "closes-when"))
                    ledger({"guard": "board", "event": "closed", "item": n, "rule": "closes-when", "cmd": cmd})
                continue
            out["held"] += 1
            continue
        if all_ticked(i):
            t, _u = boxes(i)
            since = seen.get(n, (t, now))
            if since[0] == t and now - since[1] >= stale_hours * 3600:
                hrs = int((now - since[1]) // 3600)
                why = f"CLOSED {utc()} by the board: all {t} boxes ticked for {hrs}h (crew#526)"
                if not post or close_issue(n, why):
                    out["closed"].append((n, "all-ticked"))
                    ledger({"guard": "board", "event": "closed", "item": n, "rule": "all-ticked", "hours": hrs})
                continue
            out["held"] += 1
            continue
        if awaiting_receipt(i):
            out["awaiting_receipt"] += 1
            continue
        out["no_rule"] += 1
    return out


def log_close_pass(r: dict, open_count: int, path: str = CLOSER_LOG) -> None:
    """One line per turn to the science log (crew#526: counts land where velocity reads them)."""
    if not path:
        return
    row = {"ts": utc(), "open": open_count, "closed": len(r["closed"]), "ran": r["ran"],
           "held": r["held"], "no_rule": r["no_rule"], "refused": r.get("refused", 0),
           "awaiting_receipt": r.get("awaiting_receipt", 0),
           "by_rule": {k: sum(1 for _, w in r["closed"] if w == k) for k in ("closes-when", "all-ticked")}}
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


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


def reply_opens_blocked(text: str) -> bool:
    """True when an agent reply opens with BLOCKED:, ignoring the markdown a reply-format law
    itself teaches (`BLOCKED:`, **BLOCKED:**). 2026-08-28: a session declared a validated
    BLOCKED: four times in a row inside backticks and idle-guard v2 refused every one, because
    startswith() saw the backtick first. The escape existed and could not be reached."""
    return text.lstrip().lstrip("`*_# ").startswith(BLOCKED)


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
            {"number": 60, "title": "half done", "labels": [], "assignees": [], "comments": [],
             "body": "- [x] a\n- [x] b\n- [ ] c"},
            {"number": 70, "title": "blocked", "labels": ["P0"], "assignees": [], "comments": [],
             "body": "Blocked-on: #50\n- [x] a\n- [ ] b"},
            {"number": 80, "title": "p1 untouched", "labels": ["P1"], "assignees": [], "comments": []},
        ]
        d = tempfile.mkdtemp()
        p = Path(d) / "fx.json"; p.write_text(json.dumps(fx))
        os.environ["ESTATE_BOARD_FIXTURE"] = str(p)
        items = [i["number"] for i in unclaimed(open_issues())]
        ck("meta, claimed, assigned and epic are skipped; finish-first: half done, then P1, then oldest, blocked last",
           items == [60, 80, 30, 50, 70])
        ck("next unclaimed is the half-done #60", next_unclaimed()["number"] == 60)
        ck("a P0 blocked on an open issue ranks last", items[-1] == 70)
        p.write_text("not json")
        ck("an unreadable board is BLIND, never empty", next_unclaimed() == "BLIND")
        p.write_text("[]")
        ck("an empty board is None", next_unclaimed() is None)
        ck("claim posts to the fixture, not gh", claim(50, "sess1234abcd", "code", "why")
           and "CLAIM " in open(str(p) + ".posted.jsonl").read())
        ck("founder STOP is a word", founder_word("STOP") == "STOP")
        ck("'Stop hook feedback' is not", founder_word("Stop hook feedback: x") == "")
        ck("a full BLOCKED reply has no missing field",
           blocked_missing("BLOCKED: x\nTried: a\nError: b\nNeed: c\nWho: d") == [])
        ck("a bare BLOCKED reply lists all four", blocked_missing("BLOCKED: no") == list(BLOCKED_FIELDS))
        ck("goal_number reads crew#N", goal_number("crew#306: ship it") == 306)
        # 2026-08-26 (crew#307): `estate_board.py claim 307` exited 0 and did nothing, so a P0
        # red-alert sat unowned while four sessions believed it was claimed. Unknown args refuse.
        import subprocess
        r = subprocess.run([sys.executable, __file__, "frobnicate", "1"], capture_output=True, text=True)
        ck("an unknown subcommand exits 2 and says so", r.returncode == 2 and "usage" in r.stderr)
        r = subprocess.run([sys.executable, __file__, "claim", "50", "--session", "sess1234abcd",
                            "--lane", "code", "--why", "cli"], capture_output=True, text=True,
                           env={**os.environ, "ESTATE_BOARD_FIXTURE": str(p)})
        ck("claim via CLI posts CLAIM and exits 0", r.returncode == 0 and "CLAIM" in r.stdout)
        print("PASS estate_board" if ok else "FAIL estate_board")
        sys.exit(0 if ok else 1)
    import argparse
    ap = argparse.ArgumentParser(prog="estate_board.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rk = sub.add_parser("rank", help="the board in finish-first order, top N unclaimed items")
    rk.add_argument("--top", type=int, default=20)
    cls = sub.add_parser("close", help="the board's close turn: run Closes-when lines, close all-ticked items >24h")
    cls.add_argument("--dry-run", action="store_true")
    asg = sub.add_parser("assign", help="the board's turn: release stale claims, assign alive idle sessions")
    asg.add_argument("--dry-run", action="store_true")
    for name in ("claim", "release"):
        sp = sub.add_parser(name)
        sp.add_argument("number", type=int)
        sp.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", "cli"))
        sp.add_argument("--why", default="cli")
        if name == "claim":
            sp.add_argument("--lane", default="code")
    a = ap.parse_args()
    if a.cmd == "rank":
        issues = open_issues()
        if issues is None:
            print("BLIND: the board cannot be read"); sys.exit(3)
        open_numbers = {i["number"] for i in issues}
        items = unclaimed(issues)
        print(f"finish-first rank, {len(items)} unclaimed of {len(issues)} open ({utc()})")
        for i in items[: a.top]:
            t, u = boxes(i)
            blk = blocked_on(i) & open_numbers
            lane = next((l for l in i.get("labels", []) if l.startswith("lane:")), "lane:unsorted")
            pr = next((l for l in i.get("labels", []) if l.upper() in ("P0", "P1")), "  ")
            print(f"  #{i['number']:<4} {t}/{t + u:<3} {pr:<2} {lane:<19} {'BLOCKED-ON ' + ','.join('#%d' % n for n in sorted(blk)) if blk else ''} {i['title'][:60]}")
        sys.exit(0)
    if a.cmd == "close":
        issues = open_issues()
        if issues is None:
            print("BLIND: the board cannot be read"); sys.exit(3)
        work = [i for i in issues if is_work(i)]
        r = close_pass(work, time.time(), _last_boxes_seen(), os.getcwd(), post=not a.dry_run)
        if not a.dry_run:
            log_close_pass(r, len(issues) - len(r["closed"]))
        print(f"board close ({'dry-run' if a.dry_run else 'posted'}) {utc()}: {len(issues)} open; "
              f"closed {', '.join(f'#{n} ({w})' for n, w in r['closed']) or '-'}; "
              f"ran {r['ran']} Closes-when line(s); refused {r['refused']}; held {r['held']}; "
              f"no rule {r['no_rule']} " +
              f"awaiting founder receipt {r.get('awaiting_receipt', 0)}")
        sys.exit(0)
    if a.cmd == "assign":
        issues = open_issues()
        if issues is None:
            print("BLIND: the board cannot be read"); sys.exit(3)
        feed = FEED.read_text() if FEED.is_file() else ""
        now = time.time()
        alive = alive_sessions(feed, now)
        r = assign(issues, alive, now, _last_boxes_seen(), post=not a.dry_run)
        print(f"board assign ({'dry-run' if a.dry_run else 'posted'}) {utc()}: {len(alive)} alive session(s) "
              f"{', '.join(sorted(alive)) or '-'}; released {r['released'] or '-'}; "
              f"assigned {', '.join(f'{s}->#{n}' for s, n in r['assigned']) or '-'}; "
              f"holding {', '.join(f'{s}:{v}' for s, v in sorted(r['held'].items())) or '-'}")
        if not feed:
            print(f"BLIND: no feed at {FEED}; nobody is alive to the board"); sys.exit(3)
        sys.exit(0)
    okp = (claim(a.number, a.session, a.lane, a.why) if a.cmd == "claim"
           else release(a.number, a.session, a.why))
    print(f"{'CLAIM' if a.cmd == 'claim' else 'RELEASE'} crew#{a.number} {'posted' if okp else 'FAILED'}")
    sys.exit(0 if okp else 1)
