#!/usr/bin/env python3
"""Nothing for the founder goes into the void: a DONE: reply that links a deliverable is sent to
his Telegram, with the links, by the machine and not by a session remembering to.

WHY. 2026-08-25 a session wrote crew/docs/RESEARCH_PLATFORM_CAPABILITY.md, pushed it and posted
it on crew #221. He runs several sessions at once and never saw it. His words: "currently im blind
to what was researched", "nothing can ever go into the void", "should have reached me on telegram
... or a link where i can see it directly so i can evaluate proposal and consult and decide",
"everything needs to be on tap". The sender existed (estate/estate_alert.py, with ledger and
debounce); nothing called it for a deliverable. Writing was the half that existed; this is the
delivery half, on Stop, where a session cannot walk past it.

THE CLASS. A deliverable addressed to the founder that lands only where he is not looking (a repo,
an issue, a file). Instance of crew#164's class: the thing was produced and nothing said so.

WHAT COUNTS AS A DELIVERABLE. The final reply opens DONE: and contains at least one link he can
open: a GitHub issue/PR/blob/commit URL, a claude.ai artifact URL, or a repo doc path
(`something/docs/NAME.md`). Plain DONE: replies with no link are not sent; that would be noise, and
the channel was already "too noisy to find anything useful in" (telegram_ledger.py).

ONE MESSAGE PER DELIVERABLE. A set of links is sent once; state lives in
~/.claude/state/founder-deliver.json. Re-stating the same link in a later reply does not re-send.

NEVER BLOCKS. Exit 0 always. A delivery hook that stops a turn is an outage (LAW 38). If the
sender is unavailable it prints BLIND, never a verdict.

Selftest: `python3 founder-deliver.py --selftest` proves one must-send and one must-not-send in
the same run, with the sender stubbed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
STATE = HOME / ".claude" / "state" / "founder-deliver.json"
SCRIPTS = HOME / ".claude" / "scripts"

LINK_RE = re.compile(
    r"(https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull|blob|commit)/[^\s)>\]`]+"
    r"|https://claude\.ai/code/artifact/[^\s)>\]`]+"
    r"|(?<![\w/])[\w.-]+/docs/[\w./-]+\.md)"
)
MAX_LINKS = 5
MAX_HEAD = 300


def last_assistant_text(transcript: Path) -> str:
    text = ""
    try:
        with transcript.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") != "assistant":
                    continue
                content = (row.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                parts = [b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text"]
                joined = "\n".join(p for p in parts if p).strip()
                if joined:
                    text = joined
    except OSError:
        return ""
    return text


def deliverable(text: str) -> tuple[str, list[str]] | None:
    """(headline, links) when the reply is a DONE: with links he can open, else None."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("DONE:"):
        return None
    above = text.split("\n---", 1)[0]
    links: list[str] = []
    for m in LINK_RE.finditer(text):
        u = m.group(0).rstrip(".,;:")
        if u not in links:
            links.append(u)
    if not links:
        return None
    head = lines[0][:MAX_HEAD]
    body = " ".join(above.splitlines()[1:]).strip()
    if body:
        head += "\n" + body[:MAX_HEAD]
    return head, links[:MAX_LINKS]


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(state: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(STATE)
    except Exception:  # noqa: BLE001
        pass


def _send_real(text: str, delivery_id: str) -> bool:
    """Post the receipt to his DM with three decision buttons, and ledger it.

    Not estate_alert.send_operator_alert: with TELEGRAM_ALERT_CHANNEL unset that function
    writes to ~/.estate/alerts/inbox.jsonl and returns True. The #221 proposal went there on
    2026-08-25 and he never saw it. A receipt for a decision goes to the DM, by name.
    The buttons are estate:decide:<id>:<verdict>; the hermes gateway's operator shell
    handles estate:* taps (gateway/operator_shell/estate.py) and records the verdict.
    """
    import urllib.request
    sys.path.insert(0, str(SCRIPTS / "estate"))
    try:
        import estate_alert  # type: ignore
        import telegram_ledger  # type: ignore
    except Exception:  # noqa: BLE001
        print("[founder-deliver] BLIND: estate_alert unavailable, nothing sent", file=sys.stderr)
        return False
    token = estate_alert._env("TELEGRAM_BOT_TOKEN")
    chat = estate_alert._env("TELEGRAM_HOME_CHANNEL")
    if not token or not chat:
        print("[founder-deliver] BLIND: no TELEGRAM_BOT_TOKEN/TELEGRAM_HOME_CHANNEL", file=sys.stderr)
        telegram_ledger.record("founder-deliver", "no-creds", text, key=delivery_id)
        return False
    payload = json.dumps({
        "chat_id": chat, "text": text[:4000], "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[
            {"text": "\u2705 Go", "callback_data": f"estate:decide:{delivery_id}:go"},
            {"text": "\U0001f501 Rework", "callback_data": f"estate:decide:{delivery_id}:rework"},
            {"text": "\U0001f4d6 Read later", "callback_data": f"estate:decide:{delivery_id}:later"},
        ]]},
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.load(r)
        mid = (body.get("result") or {}).get("message_id")
    except Exception as exc:  # noqa: BLE001
        print("[founder-deliver] BLIND: send failed: %s" % exc, file=sys.stderr)
        telegram_ledger.record("founder-deliver", "failed", text, key=delivery_id)
        return False
    telegram_ledger.record("founder-deliver", "sent" if mid else "failed", text, key=delivery_id)
    return bool(mid)


def delivery_id(links: list[str]) -> str:
    import hashlib
    return hashlib.sha1(links[0].encode()).hexdigest()[:12]


def handle(payload: dict, send=_send_real, state_path: Path = STATE) -> str:
    """Returns 'sent', 'skip', 'dup' or 'blind'. Never raises."""
    global STATE
    STATE = state_path
    path = payload.get("transcript_path") or ""
    if not path:
        return "skip"
    found = deliverable(last_assistant_text(Path(path)))
    if not found:
        return "skip"
    head, links = found
    state = _load()
    sent = state.setdefault("sent", {})
    fresh = [u for u in links if u not in sent]
    if not fresh:
        return "dup"
    session = str(payload.get("session_id") or "")[:8]
    did = delivery_id(fresh)
    msg = "[receipt %s] session %s\n%s\n\n%s\n\nTap one. The verdict lands on the issue and the board." % (
        did, session, head, "\n".join(fresh))
    ok = send(msg, did)
    if not ok:
        return "blind"
    for u in fresh:
        sent[u] = True
    import time as _t
    state.setdefault("deliveries", []).append(
        {"id": did, "ts": _t.time(), "session": session, "head": head.splitlines()[0][:MAX_HEAD],
         "links": fresh, "decision": None})
    state["deliveries"] = state["deliveries"][-50:]
    _save(state)
    return "sent"


def _gh_comment(issue_url: str, body: str) -> bool:
    import subprocess
    url = issue_url.split("#", 1)[0]
    try:
        r = subprocess.run(["gh", "issue", "comment", url, "--body", body],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


VERDICTS = {"go": "GO", "rework": "REWORK", "later": "READ LATER"}


def decide(did: str, verdict: str, by: str = "founder", state_path: Path = STATE,
           gh=_gh_comment) -> str:
    """Record his tap on a receipt, and put it where the crew reads: the GitHub issue.

    One hop from any device: the receipt has three buttons, the tap lands here through the
    Telegram adapter (plugins/platforms/telegram/adapter.py, `fd:` branch), the verdict is
    written to the delivery record (the board reads it) and posted on the linked issue.
    Returns the one line the adapter writes under the receipt. Never raises.
    """
    global STATE
    STATE = state_path
    if verdict not in VERDICTS:
        return "unknown verdict %r" % verdict
    state = _load()
    d = next((x for x in state.get("deliveries", []) if x.get("id") == did), None)
    if d is None:
        return "no delivery %s on record; nothing changed" % did
    import time as _t
    d["decision"] = {"verdict": verdict, "ts": _t.time(), "by": by}
    _save(state)
    issue = next((u for u in d.get("links", []) if "/issues/" in u), None)
    line = "%s %s recorded for receipt %s." % ("\u2705", VERDICTS[verdict], did)
    if issue and verdict != "later":
        ok = gh(issue, "Founder decision: **%s** (tapped on Telegram receipt %s by %s). "
                       "Crew acts on this. Do not ask him again." % (VERDICTS[verdict], did, by))
        line += " Posted on %s." % issue.split("#")[0] if ok else " NOT posted on %s (gh failed)." % issue.split("#")[0]
    return line


ISSUE_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/issues/\d+|(?<![\w/])crew ?#(\d+)\b")
DOC_REPO_URL = "https://github.com/chidionyema/%s/blob/main/%s"


def attach(text: str, gh=None, state_path: Path = STATE) -> str:
    """Founder, 2026-08-25: "save doc attached to ticket, should be auto". Any reply opening
    DONE:/INVENTORY: that names an issue and a doc (repo doc path, blob URL or artifact) gets the
    doc links posted on that issue, once per (issue, link). Returns 'attached', 'skip' or 'dup'."""
    global STATE
    STATE = state_path
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not (lines[0].startswith("DONE:") or lines[0].startswith("INVENTORY:")):
        return "skip"
    issue = None
    for m in ISSUE_RE.finditer(text):
        issue = ("https://github.com/chidionyema/crew/issues/" + m.group(1)) if m.group(1) else m.group(0).split("#")[0]
        break
    if not issue:
        return "skip"
    docs = []
    for m in LINK_RE.finditer(text):
        u = m.group(0).rstrip(".,;:")
        if "/issues/" in u or "/pull/" in u or "/commit/" in u:
            continue
        if not u.startswith("http"):
            repo, _, rel = u.partition("/")
            u = DOC_REPO_URL % (repo, rel)
        if u not in docs:
            docs.append(u)
    if not docs:
        return "skip"
    state = _load()
    seen = state.setdefault("attached", {})
    fresh = [u for u in docs if seen.get(issue + " " + u) is None]
    if not fresh:
        return "dup"
    body = "Attached (auto, founder-deliver):\n" + "\n".join("- " + u for u in fresh)
    if not (gh or _gh_comment)(issue, body):
        return "blind"
    for u in fresh:
        seen[issue + " " + u] = True
    _save(state)
    return "attached"


def selftest() -> int:
    import tempfile
    fails = 0
    calls: list[str] = []

    def fake(text, did):
        calls.append(text)
        return True

    def transcript(d: Path, reply: str) -> Path:
        t = d / "t.jsonl"
        t.write_text(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": reply}]}}) + "\n", encoding="utf-8")
        return t

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        st = d / "state.json"
        must_send = ("DONE: the proposal is written and posted.\n"
                     "Doc: crew/docs/RESEARCH_PLATFORM_CAPABILITY.md and "
                     "https://github.com/chidionyema/crew/issues/221#issuecomment-1\n---\nevidence")
        r1 = handle({"transcript_path": str(transcript(d, must_send)), "session_id": "abc"},
                    send=fake, state_path=st)
        ok1 = r1 == "sent" and len(calls) == 1 and "issues/221" in calls[0] \
            and "crew/docs/RESEARCH_PLATFORM_CAPABILITY.md" in calls[0]
        print("must-send  ", "PASS" if ok1 else "FAIL (%s, %d calls)" % (r1, len(calls)))
        fails += not ok1

        r2 = handle({"transcript_path": str(transcript(d, must_send)), "session_id": "abc"},
                    send=fake, state_path=st)
        ok2 = r2 == "dup" and len(calls) == 1
        print("no-resend  ", "PASS" if ok2 else "FAIL (%s)" % r2)
        fails += not ok2

        must_not = "DONE: killed two find processes and quit Chrome. Load 236 to 67.\n---\nuptime"
        r3 = handle({"transcript_path": str(transcript(d, must_not)), "session_id": "abc"},
                    send=fake, state_path=st)
        ok3 = r3 == "skip" and len(calls) == 1
        print("must-not   ", "PASS" if ok3 else "FAIL (%s)" % r3)
        fails += not ok3

        working = "WORKING: drafting crew/docs/X.md, https://github.com/o/r/issues/1"
        r4 = handle({"transcript_path": str(transcript(d, working)), "session_id": "abc"},
                    send=fake, state_path=st)
        ok4 = r4 == "skip" and len(calls) == 1
        print("not-done   ", "PASS" if ok4 else "FAIL (%s)" % r4)
        fails += not ok4

        r5 = handle({"transcript_path": str(transcript(d, "DONE: x https://github.com/o/r/pull/9")),
                     "session_id": "abc"}, send=lambda t, d: False, state_path=st)
        ok5 = r5 == "blind"
        print("blind      ", "PASS" if ok5 else "FAIL (%s)" % r5)
        fails += not ok5
        posted: list[str] = []
        r6 = decide("nope", "go", state_path=st, gh=lambda u, b: posted.append(u) or True)
        ok6 = r6.startswith("no delivery") and not posted
        print("decide-miss", "PASS" if ok6 else "FAIL (%s)" % r6)
        fails += not ok6
        did = json.loads(st.read_text())["deliveries"][0]["id"]
        r7 = decide(did, "go", by="t", state_path=st, gh=lambda u, b: posted.append(u) or True)
        rec = json.loads(st.read_text())["deliveries"][0]["decision"]
        ok7 = "GO recorded" in r7 and posted == ["https://github.com/chidionyema/crew/issues/221#issuecomment-1"] \
            and rec["verdict"] == "go"
        print("decide-go  ", "PASS" if ok7 else "FAIL (%s %s)" % (r7, posted))
        fails += not ok7
        r8 = decide(did, "later", state_path=st, gh=lambda u, b: posted.append(u) or True)
        ok8 = "READ LATER" in r8 and len(posted) == 1
        print("decide-late", "PASS" if ok8 else "FAIL (%s)" % r8)
        fails += not ok8
        posted_att: list[tuple[str, str]] = []
        ga = lambda u, b: posted_att.append((u, b)) or True  # noqa: E731
        ra = attach("INVENTORY: doc written.\nBuilt: crew/docs/rulings/R31-x.md for crew #221\n",
                    gh=ga, state_path=st)
        oka = ra == "attached" and posted_att and posted_att[0][0].endswith("/crew/issues/221") \
            and "crew/blob/main/docs/rulings/R31-x.md" in posted_att[0][1]
        print("attach-must", "PASS" if oka else "FAIL (%s %s)" % (ra, posted_att))
        fails += not oka
        rb = attach("INVENTORY: doc written.\nBuilt: crew/docs/rulings/R31-x.md for crew #221\n",
                    gh=ga, state_path=st)
        okb = rb == "dup" and len(posted_att) == 1
        print("attach-dup ", "PASS" if okb else "FAIL (%s)" % rb)
        fails += not okb
        rc = attach("INVENTORY: no doc here, https://github.com/chidionyema/crew/issues/221\n",
                    gh=ga, state_path=st)
        rd = attach("WORKING: crew/docs/x.md on crew #221\n", gh=ga, state_path=st)
        okc = rc == "skip" and rd == "skip" and len(posted_att) == 1
        print("attach-not ", "PASS" if okc else "FAIL (%s %s)" % (rc, rd))
        fails += not okc
    print("founder-deliver selftest: %d failures" % fails)
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--decide" in sys.argv:
        i = sys.argv.index("--decide")
        by = sys.argv[sys.argv.index("--by") + 1] if "--by" in sys.argv else "founder"
        try:
            print(decide(sys.argv[i + 1], sys.argv[i + 2], by=by))
        except Exception as exc:  # noqa: BLE001
            print("decision not recorded: %s" % exc)
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    try:
        verdict = handle(payload)
        if verdict in ("sent", "blind"):
            print("[founder-deliver] %s" % verdict, file=sys.stderr)
        path = payload.get("transcript_path") or ""
        if path:
            att = attach(last_assistant_text(Path(path)))
            if att in ("attached", "blind"):
                print("[founder-deliver] attach %s" % att, file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print("[founder-deliver] BLIND: %s" % exc, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
