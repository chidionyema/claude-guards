#!/usr/bin/env python3
"""Every session carries a GitHub issue, or it does not get to change anything.

Founder, 2026-08-23: "i tnothin no ework should ever be done without a ticket and it should be
autonated", "is should be inpossi ble to work without a ticket", "that is a github issue",
"because i an pronting different agent sessions", "so nay things get started and not folloed up".

The failure this closes, measured the same day: he asked a session to get aiden operational, no
issue was ever opened, and by the time he asked again nobody could say which tab held it. Aiden
was in fact running the whole time. The work was fine. The thread was gone.

HOW IT WORKS, and why it never costs him or an agent a single command:

  1. A session's first mutating tool call arrives with no ticket bound.
  2. This hook does NOT ask anyone for one. It reads the founder's own first words out of that
     session's transcript, spawns a detached child that opens the issue, and lets the call
     through. The hook itself returns in milliseconds and never touches the network.
  3. The child writes ~/.claude/state/tickets/<session>.json. Every later call reads that file.
  4. If the child failed, the NEXT mutating call is refused with exit 2. That is the "impossible"
     part, and it lands on the agent, never on him.

Fail-open everywhere except that one case. A guard that wedges fifteen live sessions because
GitHub was slow is a worse defect than the one it prevents.

Modes:
  (no args)      PreToolUse hook. Reads the payload on stdin.
  --roster       Print every live session with its ticket. What aiden puts on his phone.
  --selftest     Prove the decision table without touching the network.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
TICKETS = os.path.join(HOME, ".claude", "state", "tickets")
REPO = "chidionyema/crew"

#: Tools that change the world. A read never needs a ticket: he is not trying to stop an agent
#: from looking at a file, he is trying to stop work from happening off the board.
MUTATING = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

#: A Bash command only needs a ticket if it writes. Grepping for a symbol is reading.
#: The redirect alternative sits outside the \b group on purpose: > is not a word character, so a
#: leading \b can never match in front of it and the whole branch would be dead.
BASH_WRITES = re.compile(
    r"\b(git (commit|push|merge|rebase|reset|checkout -b)|gh (pr|issue|release)"
    r"|fly (deploy|secrets|scale)|rm |mv |cp |tee |chmod |chown |launchctl "
    r"|pip install|npm install)"
    r"|>>?\s*[^\s|&]",
)

#: How long a creation attempt may be in flight before the next call stops waiting for it and
#: refuses. Long enough for a slow `gh`, short enough that a dead child cannot hold the gate open.
INFLIGHT_S = 90


def _read_payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def _needs_ticket(tool: str, tool_input: dict) -> bool:
    if tool in MUTATING:
        return True
    if tool == "Bash":
        return bool(BASH_WRITES.search(tool_input.get("command", "")))
    return False


def founder_words(transcript: str) -> str:
    """The first thing the founder actually typed in this session. Hook text arrives with
    role=user too, so it is excluded by shape, not by trusting the role field."""
    try:
        with open(transcript, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"user"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("isSidechain"):
                    continue
                msg = row.get("message") or {}
                if msg.get("role") != "user":
                    continue
                content = msg.get("content")
                text = content if isinstance(content, str) else " ".join(
                    b.get("text", "") for b in content or []
                    if isinstance(b, dict) and b.get("type") == "text")
                text = (text or "").strip()
                if not text or text[0] in "<[" or text.startswith(("Caveat:", "Stop hook")):
                    continue
                return " ".join(text.split())[:180]
    except OSError:
        pass
    return ""


def bind_path(sid: str) -> str:
    return os.path.join(TICKETS, "%s.json" % re.sub(r"[^A-Za-z0-9_-]", "", sid)[:64])


def read_bind(sid: str) -> dict | None:
    try:
        with open(bind_path(sid), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def write_bind(sid: str, data: dict) -> None:
    os.makedirs(TICKETS, exist_ok=True)
    tmp = bind_path(sid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, bind_path(sid))


def open_issue(sid: str, words: str, cwd: str) -> int:
    """Runs in the detached child. Never in the hook path."""
    title = words or "Untitled session in %s" % os.path.basename(cwd)
    if len(title) > 90:
        title = title[:87] + "..."
    body = (
        "Opened automatically when a session started changing files without a ticket.\n\n"
        "**The founder's own words, first thing he typed in this session:**\n\n> %s\n\n"
        "- working directory: `%s`\n- session: `%s`\n\n"
        "This issue exists so the work is followed up rather than lost between tabs. "
        "Close it when a command proves the outcome, not when an agent says so.\n"
        % (words or "(nothing captured)", cwd, sid)
    )
    res = subprocess.run(
        ["gh", "issue", "create", "--repo", REPO, "--title", title,
         "--body", body, "--label", "triage"],
        capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        write_bind(sid, {"issue": 0, "error": (res.stderr or "")[-300:], "at": time.time(),
                         "cwd": cwd, "words": words})
        return 1
    num = 0
    m = re.search(r"/issues/(\d+)", res.stdout or "")
    if m:
        num = int(m.group(1))
    write_bind(sid, {"issue": num, "title": title, "repo": REPO, "at": time.time(),
                     "cwd": cwd, "words": words, "url": (res.stdout or "").strip()})
    return 0


def hook() -> int:
    payload = _read_payload()
    tool = payload.get("tool_name") or ""
    if not _needs_ticket(tool, payload.get("tool_input") or {}):
        return 0
    sid = payload.get("session_id") or ""
    if not sid:
        return 0                                    # cannot identify the session: never block
    cwd = payload.get("cwd") or os.getcwd()

    bound = read_bind(sid)
    if bound and bound.get("issue"):
        return 0                                    # has a ticket, carry on

    if bound and bound.get("error"):
        sys.stderr.write(
            "TICKET GATE: this session has no GitHub issue and opening one failed.\n"
            "  %s\n"
            "No work happens off the board (founder, 2026-08-23: \"it should be impossible to "
            "work without a ticket\").\n"
            "Open one, then retry:  crew-triage  (or gh issue create --repo %s)\n"
            % (bound["error"], REPO))
        return 2

    marker = bind_path(sid) + ".inflight"
    try:
        age = time.time() - os.path.getmtime(marker)
    except OSError:
        age = None

    if age is not None and age < INFLIGHT_S:
        return 0                                    # a child is opening it right now

    os.makedirs(TICKETS, exist_ok=True)
    with open(marker, "w") as fh:
        fh.write(str(time.time()))
    words = founder_words(payload.get("transcript_path") or "")
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--create", sid, cwd, words],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return 0                                        # first call always passes


def roster() -> int:
    """Every session that has moved recently, and the ticket it is working under."""
    proj = os.path.join(HOME, ".claude", "projects")
    now = time.time()
    rows = []
    for root, _dirs, files in os.walk(proj):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(root, name)
            try:
                age = now - os.path.getmtime(path)
            except OSError:
                continue
            if age > 3 * 3600:
                continue
            sid = name[:-6]
            b = read_bind(sid) or {}
            rows.append((age, os.path.basename(root)[-20:], b.get("issue"),
                         (b.get("title") or b.get("words") or "")[:60]))
    rows.sort()
    print("%-6s %-20s %-7s %s" % ("IDLE", "WHERE", "TICKET", "WHAT HE ASKED FOR"))
    for age, where, issue, title in rows:
        tag = ("#%d" % issue) if issue else "NONE"
        print("%5.0fm %-20s %-7s %s" % (age / 60, where, tag, title))
    missing = [r for r in rows if not r[2]]
    print("\n%d live session(s), %d with no ticket" % (len(rows), len(missing)))
    return 0


DASHBOARD = os.path.join(HOME, ".claude", "state", "ops-dashboard.html")


def live_rows() -> list[dict]:
    """Every session that moved in the last three hours, with its ticket and its own last words.

    Read straight off the transcripts, because that is the one record that cannot drift from what
    a session actually did.
    """
    proj = os.path.join(HOME, ".claude", "projects")
    now = time.time()
    rows = []
    for root, _dirs, files in os.walk(proj):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(root, name)
            try:
                age = now - os.path.getmtime(path)
            except OSError:
                continue
            if age > 3 * 3600:
                continue
            sid = name[:-6]
            bind = read_bind(sid) or {}
            rows.append({
                "idle_min": age / 60,
                "where": os.path.basename(root),
                "issue": bind.get("issue") or 0,
                "error": bind.get("error", ""),
                "asked": (bind.get("words") or bind.get("title") or "")[:150],
                "said": last_words(path)[:150],
                "session": sid,
            })
    rows.sort(key=lambda r: r["idle_min"])
    return rows


def last_words(path: str) -> str:
    """The final thing the agent said in this session. Its own status line, not an inference."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 400_000))
            tail = fh.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return ""
    for line in reversed(tail):
        if '"assistant"' not in line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("isSidechain"):
            continue
        msg = row.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        text = " ".join(b.get("text", "") for b in msg.get("content") or []
                        if isinstance(b, dict) and b.get("type") == "text").strip()
        if text:
            return " ".join(text.split())
    return ""


MOVEMENT = os.path.join(HOME, ".claude", "state", "ticket-movement.json")


def movement() -> dict:
    """Every ticket and when it last moved. Founder, 2026-08-23: "i should be seeing ticketss
    noving not asking what are you doing".

    A ticket moves when GitHub's own updatedAt changes: a comment, a label, a close, a commit
    that references it. That is the estate's record of work, not an agent's claim about it.

    The last good answer is kept on disk. When `gh` fails the page still renders, and it says
    how old the numbers are rather than showing an empty board, because an empty board reads as
    "no work" and that is the one wrong thing it could say.
    """
    try:
        raw = subprocess.run(
            ["gh", "issue", "list", "--repo", REPO, "--state", "all", "--limit", "80",
             "--json", "number,title,state,updatedAt,createdAt,labels"],
            capture_output=True, text=True, timeout=45)
        items = json.loads(raw.stdout) if raw.returncode == 0 else None
    except Exception:
        items = None
    if items is None:
        try:
            with open(MOVEMENT, encoding="utf-8") as fh:
                stale = json.load(fh)
            stale["stale"] = True
            return stale
        except Exception:
            return {"items": [], "at": 0, "stale": True}
    data = {"items": items, "at": time.time(), "stale": False}
    tmp = MOVEMENT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, MOVEMENT)
    return data


def _age_h(stamp: str) -> float:
    """Hours since an ISO8601 GitHub timestamp. Returns a large number when it cannot be read,
    so an unparseable date sorts as stuck rather than as fresh."""
    try:
        t = time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return 9e9
    return (time.time() - calendar.timegm(t)) / 3600.0


def counts(items: list[dict]) -> dict:
    """The three numbers he actually reads: what is open, what moved today, what is stuck."""
    open_ = [i for i in items if i.get("state") == "OPEN"]
    return {
        "open": len(open_),
        "moved_24h": len([i for i in items if _age_h(i.get("updatedAt", "")) < 24]),
        "closed_24h": len([i for i in items if i.get("state") == "CLOSED"
                           and _age_h(i.get("updatedAt", "")) < 24]),
        "stuck": len([i for i in open_ if _age_h(i.get("updatedAt", "")) >= 24]),
    }


def headline() -> str:
    """One line for Telegram. Ticket movement, not a question about what an agent is doing."""
    data = movement()
    c = counts(data.get("items") or [])
    tail = " (numbers are stale, gh did not answer)" if data.get("stale") else ""
    return ("TICKETS  %d open, %d moved in 24h, %d closed, %d stuck >24h%s\n"
            "         http://127.0.0.1:8787/ops" % (
                c["open"], c["moved_24h"], c["closed_24h"], c["stuck"], tail))


def dashboard() -> int:
    """Write the ops page. He opens one URL and sees the tickets moving, then every tab and the
    ticket it is on.

    Regenerated by aiden's five-minute tick, so it costs no launchd job of its own.
    """
    rows = live_rows()
    noticket = [r for r in rows if not r["issue"]]
    broken = [r for r in rows if r["error"]]

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    out = ["<title>Ops</title>", """<style>
:root{--bg:#fbfaf8;--ink:#1b1a18;--dim:#6c6862;--line:#e7e3dc;--ok:#14532d;--warn:#9a3412}
@media(prefers-color-scheme:dark){:root{--bg:#141312;--ink:#f2efe9;--dim:#9b958c;--line:#2c2a27}}
body{background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;
margin:0;padding:20px}
h1{font-size:20px;margin:0 0 4px}p.sub{color:var(--dim);margin:0 0 18px;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:11px;letter-spacing:.06em;text-transform:uppercase}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--dim)}
a{color:inherit}.tk{font-weight:600}.none{color:var(--warn);font-weight:600}
.said{color:var(--dim)}.wrap{overflow-x:auto}
.ok{color:var(--ok)}h1.second{margin-top:32px}
</style>"""]
    #: Tickets first, sessions second. He asked to see tickets moving, not to ask what an agent
    #: is doing, so the answer to "is work finishing" has to be the top of the page.
    data = movement()
    items = data.get("items") or []
    c = counts(items)
    items.sort(key=lambda i: _age_h(i.get("updatedAt", "")))
    out.append("<h1>Tickets</h1>")
    out.append("<p class=sub>%d open &middot; %d moved in 24h &middot; %d closed in 24h &middot; "
               "<b class=%s>%d stuck over 24h</b>%s</p>"
               % (c["open"], c["moved_24h"], c["closed_24h"],
                  "none" if c["stuck"] else "sub", c["stuck"],
                  " &middot; numbers are stale" if data.get("stale") else ""))
    out.append("<div class=wrap><table><tr><th>Moved</th><th>Ticket</th><th>State</th>"
               "<th>What it is</th></tr>")
    for i in items[:40]:
        h = _age_h(i.get("updatedAt", ""))
        when = "%.0fm" % (h * 60) if h < 1 else ("%.0fh" % h if h < 72 else "%.0fd" % (h / 24))
        closed = i.get("state") == "CLOSED"
        state = ("<span class=ok>closed</span>" if closed
                 else ("<span class=none>stuck</span>" if h >= 24 else "open"))
        out.append("<tr><td class=n>%s</td>"
                   "<td><a class=tk href='https://github.com/%s/issues/%d'>#%d</a></td>"
                   "<td>%s</td><td>%s</td></tr>"
                   % (when, REPO, i.get("number", 0), i.get("number", 0), state,
                      esc((i.get("title") or "")[:110])))
    out.append("</table></div>")

    out.append("<h1 class=second>Every session, and the ticket it is on</h1>")
    out.append("<p class=sub>%d live in the last 3 hours &middot; %d with no ticket &middot; "
               "%d could not open one &middot; built %s</p>"
               % (len(rows), len(noticket), len(broken),
                  time.strftime("%H:%M", time.localtime())))
    out.append("<div class=wrap><table><tr><th>Idle</th><th>Ticket</th><th>What he asked for"
               "</th><th>What it last said</th><th>Where</th></tr>")
    for r in rows:
        if r["error"]:
            tk = "<span class=none>FAILED</span>"
        elif r["issue"]:
            tk = ("<a class=tk href='https://github.com/%s/issues/%d'>#%d</a>"
                  % (REPO, r["issue"], r["issue"]))
        else:
            tk = "<span class=none>none</span>"
        out.append("<tr><td class=n>%.0fm</td><td>%s</td><td>%s</td>"
                   "<td class=said>%s</td><td class=n>%s</td></tr>"
                   % (r["idle_min"], tk, esc(r["asked"]) or "&mdash;",
                      esc(r["said"]) or "&mdash;", esc(r["where"][-24:])))
    out.append("</table></div>")
    os.makedirs(os.path.dirname(DASHBOARD), exist_ok=True)
    tmp = DASHBOARD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    os.replace(tmp, DASHBOARD)
    print("wrote %s: %d sessions, %d with no ticket" % (DASHBOARD, len(rows), len(noticket)))
    return 0


SETTINGS = os.path.join(HOME, ".claude", "settings.json")
HOOK_CMD = "python3 $HOME/.claude/scripts/ticket-gate.py"
MATCHERS = ("Edit|Write|MultiEdit|NotebookEdit", "Bash")


def switch(on: bool) -> int:
    """The off switch LAW 32 requires: one command, takes effect on the next tool call in every
    session, no restart. Kept here rather than in a README so it cannot drift from the wiring."""
    with open(SETTINGS, encoding="utf-8") as fh:
        cfg = json.load(fh)
    with open(SETTINGS + ".bak-%d" % time.time(), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    pre = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
    for m in MATCHERS:
        grp = next((g for g in pre if g.get("matcher") == m), None)
        if on:
            if grp is None:
                grp = {"matcher": m, "hooks": []}
                pre.append(grp)
            if not any(h.get("command") == HOOK_CMD for h in grp["hooks"]):
                grp["hooks"].append({"type": "command", "command": HOOK_CMD})
        elif grp is not None:
            grp["hooks"] = [h for h in grp.get("hooks", [])
                            if h.get("command") != HOOK_CMD]
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, SETTINGS)
    live = [g.get("matcher") for g in pre
            if any(h.get("command") == HOOK_CMD for h in g.get("hooks", []))]
    print("ticket gate is %s. matchers: %s"
          % ("ON" if on else "OFF", ", ".join(live) if live else "none"))
    return 0


def selftest() -> int:
    ok = fail = 0

    def check(name, got, want):
        nonlocal ok, fail
        if got == want:
            ok += 1
        else:
            fail += 1
            print("  FAIL %s: got %r want %r" % (name, got, want))

    check("Edit needs a ticket", _needs_ticket("Edit", {}), True)
    check("Write needs a ticket", _needs_ticket("Write", {}), True)
    check("Read never needs one", _needs_ticket("Read", {}), False)
    check("Grep never needs one", _needs_ticket("Grep", {}), False)
    check("bash grep is reading",
          _needs_ticket("Bash", {"command": "grep -rn foo ."}), False)
    check("bash ls is reading",
          _needs_ticket("Bash", {"command": "ls -la ~/.claude"}), False)
    check("git commit writes",
          _needs_ticket("Bash", {"command": "git commit -m x"}), True)
    check("git push writes",
          _needs_ticket("Bash", {"command": "git push origin main"}), True)
    check("redirect writes",
          _needs_ticket("Bash", {"command": "echo hi > /tmp/x"}), True)
    check("pipe alone is not a write",
          _needs_ticket("Bash", {"command": "cat x | head"}), False)
    check("fly deploy writes",
          _needs_ticket("Bash", {"command": "fly deploy -a app"}), True)
    check("rm writes", _needs_ticket("Bash", {"command": "rm -f /tmp/x"}), True)

    #: The two cases that decide whether this is a gate or a suggestion.
    import tempfile
    global TICKETS
    keep = TICKETS
    TICKETS = tempfile.mkdtemp()
    try:
        write_bind("s1", {"issue": 42})
        check("bound session passes", read_bind("s1").get("issue"), 42)
        write_bind("s2", {"error": "gh: not logged in"})
        check("failed creation is remembered", bool(read_bind("s2").get("error")), True)
        check("unknown session has no bind", read_bind("s3"), None)
    finally:
        TICKETS = keep

    print("selftest: %d/%d passed" % (ok, ok + fail))
    return 1 if fail else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--create":
        sys.exit(open_issue(sys.argv[2], sys.argv[4] if len(sys.argv) > 4 else "",
                            sys.argv[3]))
    if len(sys.argv) > 1 and sys.argv[1] in ("--off", "--on"):
        sys.exit(switch(sys.argv[1] == "--on"))
    if len(sys.argv) > 1 and sys.argv[1] == "--dashboard":
        sys.exit(dashboard())
    if len(sys.argv) > 1 and sys.argv[1] == "--roster":
        sys.exit(roster())
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    try:
        sys.exit(hook())
    except Exception:
        sys.exit(0)                                 # a broken gate never stops the estate
