#!/usr/bin/env python3
"""The estate's research trail and decision log, shared by every session and agent.

Founder, 2026-08-21: "research neans inetrnet stat with reputable sources, etc , go wide and
deep, exhautive dont leav any stone untured, docunet all sources and searches etc so tracking
decision", "deccision log also", "and how we track desicions across sessions and agents".

WHY THIS FILE EXISTS, measured rather than assumed. `~/.claude/state/prompt-ledger/` holds 1,231
real founder asks over 24 days. Every one reads `status: open`; 0 carry a spec, 0 carry acceptance
criteria, 0 carry proof. Capture worked and closing never happened. This file is the other half:
the EVIDENCE a decision rested on, and the DECISION itself, both durable and both visible to every
session -- because a session cannot see another session, so a per-session decision record is a
decision nobody else can find, which is how six agents decide the same thing six ways.

TWO ROW KINDS, one append-only JSONL, estate-level beside ESTATE_BOARD.jsonl.

  research  a question, every SEARCH run, every SOURCE read with its publisher tier and the exact
            claim it supports, the finding, the angles it rests on (LAW 15), and -- the part that
            makes "exhaustive" checkable -- the GAPS: what could not be found. "No stone unturned"
            is only a claim you may make if you can name the stones you could not turn.

  decision  the question, the options, what was chosen and why, the research rows it RESTS ON, how
            to undo it, and what would change the answer. A decision with no undo is irreversible
            and the machine demands evidence for it rather than trusting the author.

WHAT THE MACHINE REFUSES, so the principle is enforced rather than documented:
  * a research row cannot be marked `proven` on fewer than 2 sources from 2 distinct publishers --
    LAW 15, two angles that can fail differently. One source twice is one angle.
  * an irreversible decision (`--undo` empty) cannot be recorded with no `--rests-on` -- LAW 11.
  * `--check` is run BEFORE deciding and finds a standing decision on the same question, so a
    session does not re-decide what another session already settled. Same containment scoring as
    peer-loop-fence.py, at the same measured 0.55, for the same reason.

Verbs:
  --research "<question>"                                   -> new research row, prints its id
  --search  <rid> --q "<query>" [--engine web] [--n 7]      -> record one search
  --source  <rid> --url U --title T --publisher P --tier X --claim "<the sentence it supports>"
  --finding <rid> --text "..." --confidence proven|single-angle|unverifiable
                        [--angle "..."]... [--gap "..."]...
  --decide  --question Q --chose C --why W [--option O]... [--rests-on RID]...
                        [--undo "<command>"] [--revisit "<what would change the answer>"]
  --check   "<question>"      -> standing decisions that may already answer it
  --standing [--days N]       -> digest for SessionStart
  --show <id> | --list [research|decision|all] | --supersede <id> --by <id> | --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("CLAUDE_HOME") or Path.home())
LOG = Path(os.environ.get("DECISION_LOG") or (HOME / ".claude" / "DECISIONS.jsonl"))

#: Publisher tiers, worst to best. The founder asked for "reputable sources"; a machine cannot
#: judge reputation, but it CAN refuse to let a single blog post carry a decision, and it can make
#: the mix visible so a reader sees at a glance what the finding actually rests on.
TIERS = ("blog", "vendor", "news", "docs", "standard", "primary", "peer-reviewed")
CONFIDENCE = ("proven", "single-angle", "unverifiable")

#: Measured on this estate by peer-loop-fence.py: two real paraphrases of one finding scored 0.73,
#: an unrelated finding scored 0.00. Reused rather than re-derived so the two cannot drift.
MATCH = 0.55
STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "been", "it", "we", "our", "that", "this", "as", "at", "by", "from",
    "should", "do", "does", "how", "what", "why", "which", "can", "will", "would", "not",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _session() -> str:
    for var in ("CLAUDE_SESSION_ID", "CLAUDE_SESSION", "TERM_SESSION_ID"):
        v = os.environ.get(var)
        if v:
            return v[:8]
    return "unknown"


def _mkid(kind: str, text: str) -> str:
    h = hashlib.sha256(f"{kind}\x00{text}\x00{time.time_ns()}".encode()).hexdigest()
    return ("r" if kind == "research" else "d") + h[:11]


def tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-_]{2,}", (text or "").lower())
            if w not in STOP}


def containment(a: str, b: str) -> float:
    """Fraction of the SMALLER token set present in the larger. Asymmetric measures let a long
    row swallow a short one; containment on the smaller side does not."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small & large) / len(small)


def rows() -> list:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue  # a torn append must never blind the whole log
    return out


def append(row: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _latest(rid: str) -> dict | None:
    """The newest version of a row. Rows are append-only, so an update is a re-append."""
    found = None
    for r in rows():
        if r.get("id") == rid:
            found = r
    return found


def _put(row: dict) -> None:
    row["updated"] = _now()
    append(row)


# --------------------------------------------------------------------------- research

def new_research(question: str) -> int:
    row = {"id": _mkid("research", question), "kind": "research", "ts": _now(),
           "session": _session(), "question": question, "searches": [], "sources": [],
           "finding": None, "confidence": None, "angles": [], "gaps": [], "status": "open"}
    append(row)
    print(row["id"])
    return 0


def add_search(rid: str, q: str, engine: str, n: int) -> int:
    r = _latest(rid)
    if not r or r.get("kind") != "research":
        print(f"no research row {rid}", file=sys.stderr)
        return 1
    r["searches"].append({"q": q, "engine": engine, "n_results": n, "at": _now()})
    _put(r)
    print(f"{rid}: {len(r['searches'])} searches recorded")
    return 0


def add_source(rid: str, url: str, title: str, publisher: str, tier: str, claim: str) -> int:
    r = _latest(rid)
    if not r or r.get("kind") != "research":
        print(f"no research row {rid}", file=sys.stderr)
        return 1
    if tier not in TIERS:
        print(f"tier must be one of {', '.join(TIERS)}", file=sys.stderr)
        return 1
    r["sources"].append({"url": url, "title": title, "publisher": publisher, "tier": tier,
                         "claim": claim, "fetched": _now()})
    _put(r)
    print(f"{rid}: {len(r['sources'])} sources recorded")
    return 0


def set_finding(rid: str, text: str, confidence: str,
                angles: list, gaps: list) -> int:
    r = _latest(rid)
    if not r or r.get("kind") != "research":
        print(f"no research row {rid}", file=sys.stderr)
        return 1
    if confidence not in CONFIDENCE:
        print(f"confidence must be one of {', '.join(CONFIDENCE)}", file=sys.stderr)
        return 1
    pubs = {s.get("publisher", "").strip().lower() for s in r["sources"]}
    pubs.discard("")
    if confidence == "proven" and len(pubs) < 2:
        # LAW 15. Two readings from ONE publisher share that publisher's way of being wrong, so
        # they are one angle wearing two coats. This is the whole reason the check counts
        # publishers rather than sources.
        print(f"REFUSED: 'proven' needs 2+ distinct publishers, this row has {len(pubs)}. "
              f"Record it as 'single-angle' and name the second angle you would run.",
              file=sys.stderr)
        return 1
    r["finding"] = text
    r["confidence"] = confidence
    r["angles"] = list(angles)
    r["gaps"] = list(gaps)
    r["status"] = "closed"
    _put(r)
    print(f"{rid} -> closed, {confidence}, {len(r['sources'])} sources / "
          f"{len(pubs)} publishers / {len(r['searches'])} searches / {len(gaps)} gaps named")
    return 0


# --------------------------------------------------------------------------- decisions

def decide(question: str, chose: str, why: str, options: list, rests_on: list,
           undo: str, revisit: str) -> int:
    reversible = bool(undo.strip())
    if not reversible and not rests_on:
        # LAW 11 in a machine. An irreversible call with no recorded evidence is the exact shape
        # the founder has paid for twice; the log refuses it rather than recording it politely.
        print("REFUSED: this decision names no undo, so it is irreversible, and it rests on no "
              "research row. Record the evidence first (--research), or give --undo the command "
              "that puts it back.", file=sys.stderr)
        return 1
    missing = [r for r in rests_on if not _latest(r)]
    if missing:
        print(f"REFUSED: rests-on names rows that do not exist: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    row = {"id": _mkid("decision", question), "kind": "decision", "ts": _now(),
           "session": _session(), "question": question, "options": list(options),
           "chosen": chose, "why": why, "rests_on": list(rests_on),
           "reversible": reversible, "undo": undo, "revisit_when": revisit,
           "status": "standing", "superseded_by": None}
    append(row)
    print(row["id"])
    if not rests_on:
        print("  WARNING: rests on no research row. Reversible, so allowed, but a later session "
              "reading this has your conclusion and not your evidence.", file=sys.stderr)
    return 0


def supersede(old: str, new: str) -> int:
    r, n = _latest(old), _latest(new)
    if not r or r.get("kind") != "decision":
        print(f"no decision {old}", file=sys.stderr)
        return 1
    if not n:
        print(f"no row {new}", file=sys.stderr)
        return 1
    r["status"] = "superseded"
    r["superseded_by"] = new
    _put(r)
    print(f"{old} -> superseded by {new}")
    return 0


def check(question: str) -> int:
    """Run BEFORE deciding. A standing decision on the same question is the answer, and finding it
    costs one command -- far less than re-deciding it differently and discovering the split later."""
    hits = []
    seen = set()
    for r in reversed(rows()):
        if r.get("kind") != "decision" or r.get("id") in seen:
            continue
        seen.add(r["id"])
        if r.get("status") != "standing":
            continue
        score = containment(question, r.get("question", ""))
        if score >= MATCH:
            hits.append((score, r))
    if not hits:
        print("no standing decision matches. This question is open -- decide it and record it.")
        return 0
    print(f"{len(hits)} standing decision(s) may already answer this:")
    for score, r in sorted(hits, key=lambda x: -x[0]):
        print(f"  {r['id']}  match {score:.2f}  {r['ts'][:16]}  session {r.get('session')}")
        print(f"    Q: {r['question'][:110]}")
        print(f"    -> {r['chosen'][:110]}")
        if r.get("revisit_when"):
            print(f"    revisit when: {r['revisit_when'][:100]}")
    return 0


def standing(days: int) -> int:
    cutoff = time.time() - days * 86400
    latest = {}
    for r in rows():
        latest[r.get("id")] = r
    live = [r for r in latest.values()
            if r.get("kind") == "decision" and r.get("status") == "standing"
            and _epoch(r.get("ts", "")) >= cutoff]
    if not live:
        print(f"[decisions] none recorded in the last {days} days.")
        return 0
    live.sort(key=lambda r: r.get("ts", ""), reverse=True)
    print(f"[decisions] {len(live)} standing in the last {days} days. "
          f"Run `decision-log.py --check \"<your question>\"` before deciding anything.")
    for r in live[:12]:
        ev = f"{len(r.get('rests_on') or [])} research" if r.get("rests_on") else "NO EVIDENCE"
        rev = "reversible" if r.get("reversible") else "IRREVERSIBLE"
        print(f"  {r['ts'][5:16]} {r['id']} [{rev}, {ev}] {r['question'][:88]}")
        print(f"      -> {r['chosen'][:96]}")
    if len(live) > 12:
        print(f"  ... and {len(live) - 12} more not shown (cap 12) -- `--list decision` for all.")
    return 0


def _epoch(ts: str) -> float:
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return 0.0


def show(rid: str) -> int:
    r = _latest(rid)
    if not r:
        print(f"no row {rid}", file=sys.stderr)
        return 1
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0


def listing(which: str) -> int:
    latest = {}
    for r in rows():
        latest[r.get("id")] = r
    out = [r for r in latest.values() if which == "all" or r.get("kind") == which]
    out.sort(key=lambda r: r.get("ts", ""))
    for r in out:
        if r.get("kind") == "research":
            pubs = len({s.get("publisher") for s in r.get("sources") or []})
            print(f"  {r['ts'][5:16]} {r['id']} research [{r.get('confidence') or 'open'}] "
                  f"{len(r.get('searches') or [])}q/{len(r.get('sources') or [])}src/{pubs}pub "
                  f"{r['question'][:70]}")
        else:
            print(f"  {r['ts'][5:16]} {r['id']} decision [{r.get('status')}] "
                  f"{r['question'][:80]}")
    print(f"  ({len(out)} rows)")
    return 0
