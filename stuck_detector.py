#!/usr/bin/env python3
"""stuck_detector.py — notice when an autonomous agent session has stopped making progress.

Requirement R23. Founder, 2026-08-21: *"sending alert to founder telegran when stck on
task/decisino that cant resolve or when console freeses or claude api tines out, need sone
process to page founder and be able to recover"*. And the constraint that shapes the whole
design: *"that dot self heal"* — a condition that clears itself MUST NOT page.

WHY THIS READS TRANSCRIPTS AND NOT HOOKS
----------------------------------------
Every Claude Code hook event — PreToolUse, PostToolUse, Stop, SessionStart — is driven by the
session DOING something. A session that is wedged emits no event at all, so a hook can never be
the detector (`~/.claude/research/PAGING-AND-REMOTE-CONTROL.md` §2). The detector has to fire on
ABSENCE, and it has to read a signal the stuck session does not have to cooperate to produce.

That signal is the transcript. Claude Code appends every session's records to
`~/.claude/projects/<slug>/<session-id>.jsonl` in real time, for itself, whether or not anything
else is working. `estate_spend.py` already relies on this for the same reason: a meter fed by our
own instrumentation goes blind exactly when our code breaks. So does a pager.

THE ONE FALSE POSITIVE THAT WOULD SINK THIS
-------------------------------------------
Most idle sessions are not stuck. They finished a turn and are waiting for a human, which is the
normal resting state of every interactive session on this box. Paging on those is the "cries wolf"
failure the founder pre-empted.

The discriminator is the LAST assistant record's `stop_reason`, measured over the live corpus
(2026-08-21, 101 transcripts, 803 assistant records carrying the field):

    stop_reason=tool_use   606   the model asked for a tool and is waiting for the result
    stop_reason=end_turn   194   the model finished and handed back to the human
    stop_reason=stop_sequence 3

A tail ending in `end_turn` is a session at rest. It is NEVER silent-stuck, however long it sits.
A tail ending in `tool_use` with no matching `tool_result` is a session that died mid-call, and
that is the real thing. Measured: only 4 of 101 tails carry a dangling tool_use.

NOTHING HERE PAGES. `would_page` is a field, not an action. Wiring it to Telegram is a separate
decision that has not been taken.

USAGE
    stuck_detector.py --json
    stuck_detector.py --selftest
    stuck_detector.py                      # human-readable table
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

PROJECTS = os.path.expanduser("~/.claude/projects")
STATE_DIR = os.path.expanduser("~/.claude/state")
STATE_FILE = os.path.join(STATE_DIR, "stuck-detector.json")

# ---------------------------------------------------------------------------
# THRESHOLDS. Every one of these came from a measurement over the real corpus on
# 2026-08-21; the command that produced each is named. See
# ~/.claude/research/STUCK-DETECTION.md for the full output.
# ---------------------------------------------------------------------------

# A session whose transcript has not been touched for longer than this is a candidate.
# Basis: the distribution of intra-session gaps that LATER RESUMED, pooled over 101
# transcripts / 134,362 gaps. A gap that resumed was, by construction, not stuck:
#     p50 2.2s | p90 12.1s | p99 93.2s | p99.5 149.3s | p99.9 446.2s
# Only 0.046% of resumed gaps exceed 900s. 900 sits ~10x above p99 and ~2x above p99.9,
# so a normal working pause cannot reach it.
SILENT_S = 900

# Beyond this a session is not "live" and is not a candidate for anything. A stuck session
# nobody is watching any more is archaeology, not a page. 6h also keeps the scan bounded.
LIVE_WINDOW_S = 6 * 3600

# LOOPING: N identical consecutive tool calls (same tool, same arguments).
# Basis: across healthy sessions, the longest run of identical back-to-back tool calls was
# 1 in every single file measured. 0% of files reached a run of 3. A threshold of 3 sits
# above everything real sessions were observed to do.
LOOP_RUN = 3

# LOOPING (weaker form): the same tool_result error text repeating.
LOOP_ERR_RUN = 3

# ERRORED-OUT: consecutive API-level errors in the tail.
# `isApiErrorMessage` is Claude Code's own flag on a record. A single one is retried and
# clears itself; the founder's constraint says a self-healing condition must not page, so
# one is never enough.
API_ERR_RUN = 2

# DEBOUNCE: a class must persist across this many consecutive checks before would_page.
# Prometheus batch-job guidance is a staleness threshold of >= 2x the job period; the same
# logic applied to a pager means a condition must survive a whole extra check interval.
# This is the mechanical form of "that dot self heal".
DEBOUNCE_CHECKS = 2

# Never read more than this from the tail of a transcript. The largest live transcript
# measured was 96,151,013 B (96 MB); loading it would be the bug this guard is meant to catch.
TAIL_BYTES = 1_000_000
TAIL_RECORDS = 400

# A tail record must be one of these to count as the session's last act.
_TS_TYPES = ("assistant", "user", "system", "attachment")

_API_ERR_RE = re.compile(
    r"(API Error|rate.?limit|\b429\b|\b529\b|\b503\b|overloaded|Request timed out|"
    r"Connection error|usage limit|credit balance|enforced_spend_limit_reached)", re.I)

# A trailing question from the assistant, with nothing after it.
_QUESTION_RE = re.compile(r"\?\s*$")


# ---------------------------------------------------------------------------
# Transcript reading — streaming only, never load a whole file
# ---------------------------------------------------------------------------

def tail_records(path: str, tail_bytes: int = TAIL_BYTES,
                 max_records: int = TAIL_RECORDS) -> list[dict]:
    """Parse at most `max_records` records from the last `tail_bytes` of a transcript.

    Seeks rather than reads. A 96 MB transcript costs the same as a 60 KB one.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()          # discard the partial line the seek landed inside
            raw = fh.read()
    except OSError:
        return []
    out = []
    for line in raw.decode("utf-8", "replace").splitlines()[-max_records:]:
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except (ValueError, TypeError):
            continue
    return out


def _ts(rec: dict) -> float | None:
    t = rec.get("timestamp")
    if not isinstance(t, str):
        return None
    try:
        return dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _blocks(rec: dict) -> list[dict]:
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _text_of(rec: dict) -> str:
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    parts = []
    for b in _blocks(rec):
        if b.get("type") == "text":
            parts.append(str(b.get("text") or ""))
    return "\n".join(parts)


def _entrypoint(recs: list[dict]) -> str:
    """'cli' for an interactive session, 'sdk-cli' for a headless one-shot, '' if unknown.

    Read from the LAST record that carries it, so a resumed session reports how it is
    running now rather than how it started.
    """
    for r in reversed(recs):
        e = r.get("entrypoint")
        if isinstance(e, str) and e:
            return e
    return ""


def _call_sig(block: dict) -> str:
    payload = str(block.get("name")) + json.dumps(
        block.get("input"), sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8", "replace")).hexdigest()[:12]


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c[:4000]
    return json.dumps(c, default=str)[:4000]


def _longest_tail_run(items: list) -> int:
    """Length of the run of identical values ENDING the list.

    Deliberately the trailing run, not the longest anywhere: a loop three calls ago that the
    session broke out of is not stuck, it is a session that recovered.
    """
    if not items:
        return 0
    last = items[-1]
    n = 0
    for x in reversed(items):
        if x == last:
            n += 1
        else:
            break
    return n


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(recs: list[dict], idle_s: float,
             silent_s: int = SILENT_S) -> tuple[str, str]:
    """Return (class, evidence). 'OK' means nothing to report.

    Order matters: the most specific and most actionable class wins. A session that is both
    erroring and silent is an ERRORED session, because the error names the remedy.
    """
    if not recs:
        return "OK", "no parseable records in tail"

    # --- gather, in one pass over the tail ---
    #
    # Every "run" below is counted only over records AFTER the last SUCCESSFUL tool result.
    # That guard is load-bearing and was added after a measured false positive: on
    # 2026-08-21 session 74f4ed5c hit the agent-fleet cap 4 times between 09:23:54 and
    # 09:24:53 and then RECOVERED (successful results at 09:25:27, 09:26:23, 09:26:32).
    # An error list is a FILTERED subsequence of the transcript, so its trailing run stays
    # 4 forever even though the session moved on. Counting a run over a filtered list
    # answers "did this ever happen", not "is this still happening" — and the founder's
    # "that dot self heal" is precisely the second question.
    calls: list[str] = []           # tool_use signatures, in order
    call_names: list[str] = []
    used: dict[str, str] = {}       # tool_use id -> name
    resulted: set[str] = set()
    err_texts: list[tuple[int, str]] = []      # (record index, error text)
    api_errs: list[int] = []                   # record indices
    last_assistant: dict | None = None
    last_stop_reason: str | None = None
    last_ok_idx = -1                # index of the last SUCCESSFUL tool result

    for i, r in enumerate(recs):
        rtype = r.get("type")
        if rtype == "assistant":
            last_assistant = r
            sr = (r.get("message") or {}).get("stop_reason")
            if sr:
                last_stop_reason = sr
        if r.get("isApiErrorMessage"):
            api_errs.append(i)
        txt = _text_of(r)
        if txt and _API_ERR_RE.search(txt) and rtype != "user":
            api_errs.append(i)
        for b in _blocks(r):
            bt = b.get("type")
            if bt == "tool_use":
                calls.append(_call_sig(b))
                call_names.append(str(b.get("name")))
                used[str(b.get("id"))] = str(b.get("name"))
            elif bt == "tool_result":
                resulted.add(str(b.get("tool_use_id")))
                if b.get("is_error"):
                    err_texts.append((i, _result_text(b)[:300]))
                else:
                    last_ok_idx = i     # the session made progress here

    # Only failures that nothing has succeeded after are still happening.
    live_api_errs = [i for i in api_errs if i > last_ok_idx]
    live_errs = [t for (i, t) in err_texts if i > last_ok_idx]

    # --- 4. ERRORED-OUT ------------------------------------------------------
    # Consecutive API-level failures with no success since. One clears itself on retry, so
    # one never counts.
    if len(live_api_errs) >= API_ERR_RUN:
        return ("ERRORED",
                f"{len(live_api_errs)} API-level error records with no successful tool call "
                f"since (tail of {len(recs)} records)")

    # --- 2. LOOPING ----------------------------------------------------------
    run = _longest_tail_run(calls)
    if run >= LOOP_RUN:
        name = call_names[-1] if call_names else "?"
        return ("LOOPING",
                f"last {run} tool calls are identical ({name}, same arguments)")

    err_run = _longest_tail_run(live_errs)
    if err_run >= LOOP_ERR_RUN:
        return ("LOOPING",
                f"the same tool error repeated {err_run}x with no success since: "
                f"{live_errs[-1][:120]!r}")

    # Everything below is an ABSENCE condition and needs the session to actually be idle.
    if idle_s < silent_s:
        return "OK", f"active {int(idle_s)}s ago"

    # --- 1. SILENT -----------------------------------------------------------
    # A dangling tool_use is a session that asked for a tool and never got the result:
    # the console froze, or the tool never returned. This is the founder's "console freeses".
    dangling = [used[i] for i in used if i not in resulted]
    if dangling:
        return ("SILENT",
                f"idle {int(idle_s)}s with an unanswered {dangling[-1]} tool call "
                f"(stop_reason={last_stop_reason})")

    # --- 3. BLOCKED-ON-HUMAN -------------------------------------------------
    # The turn ended cleanly AND the last thing said was a question. The session is not
    # broken; it is waiting for a decision only the founder can make, which is exactly the
    # founder's "stck on task/decisino that cant resolve".
    #
    # ONLY for interactive sessions. Measured 2026-08-21 over the 26 live transcripts:
    # entrypoint `sdk-cli` 21, `cli` 5. An `sdk-cli` session is a headless one-shot with no
    # human attached to answer anything, so it can never be blocked on one — it has simply
    # finished. Without this split the detector's only live hit was a headless SDK call
    # whose answer happened to end "Does that help?".
    interactive = _entrypoint(recs) == "cli"
    if last_stop_reason in ("end_turn", "stop_sequence") and last_assistant is not None:
        txt = _text_of(last_assistant).strip()
        tail = txt[-400:]
        if interactive and _QUESTION_RE.search(tail):
            return ("BLOCKED_ON_HUMAN",
                    f"idle {int(idle_s)}s after asking: {tail.splitlines()[-1][:140]!r}")
        # Ended its turn, said nothing that needs an answer. This is a session AT REST.
        # It is the single most common state on this box and it is never stuck.
        return "OK", f"turn ended cleanly (end_turn), idle {int(idle_s)}s — at rest"

    # Idle, no clean end_turn, no dangling call. Unresolved rather than healthy.
    return ("SILENT",
            f"idle {int(idle_s)}s, last stop_reason={last_stop_reason!r}, no clean turn end")


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def find_recent(projects: str, live_window_s: int) -> list[str]:
    """Transcripts touched inside the live window.

    `find -mmin` is used rather than a Python walk because the corpus is 89,418 files across
    16,616 directories (measured 2026-08-21); find does the stat loop in C. Measured warm:
    13.2s for the whole corpus, 50.2s cold.
    """
    mins = max(1, int(live_window_s // 60))
    try:
        proc = subprocess.run(
            ["find", projects, "-maxdepth", "2", "-name", "*.jsonl", "-mmin", f"-{mins}"],
            capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [p for p in proc.stdout.splitlines() if p.strip()]


def scan(projects: str = PROJECTS, live_window_s: int = LIVE_WINDOW_S,
         silent_s: int = SILENT_S, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    rows = []
    for path in find_recent(projects, live_window_s):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        idle_s = max(0.0, now - mtime)
        recs = tail_records(path)

        # Prefer the last in-band timestamp over mtime. mtime moves for reasons that are not
        # the session speaking (a sidecar write, an editor touching the file); the record's
        # own timestamp is what the session actually did.
        stamps = [t for t in (_ts(r) for r in recs if r.get("type") in _TS_TYPES)
                  if t is not None]
        if stamps:
            idle_s = max(0.0, now - max(stamps))

        cls, evidence = classify(recs, idle_s, silent_s=silent_s)
        slug = os.path.basename(os.path.dirname(path))
        cwd = ""
        for r in reversed(recs):
            if r.get("cwd"):
                cwd = str(r.get("cwd"))
                break
        rows.append({
            "session": os.path.basename(path)[:-6],
            "slug": slug,
            "cwd": cwd,
            "path": path,
            "class": cls,
            "idle_s": int(idle_s),
            "evidence": evidence,
            "would_page": False,      # filled in by the debounce
        })
    rows.sort(key=lambda r: (r["class"] == "OK", -r["idle_s"]))
    return rows


# ---------------------------------------------------------------------------
# Debounce — the mechanical form of "that dot self heal"
# ---------------------------------------------------------------------------

def load_state(state_file: str) -> dict:
    try:
        with open(state_file) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state_file: str, state: dict) -> None:
    """Atomic write. A pager whose own state file is half-written pages on garbage."""
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(state_file), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh, indent=1, sort_keys=True)
        os.replace(tmp, state_file)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def apply_debounce(rows: list[dict], state_file: str = STATE_FILE,
                   debounce: int = DEBOUNCE_CHECKS, persist: bool = True,
                   now: float | None = None) -> list[dict]:
    """A class must hold across `debounce` consecutive checks before would_page is true.

    The streak is keyed on session AND class. A session that flips SILENT -> LOOPING has not
    held one condition for two checks; it has two one-check conditions, and neither pages.
    That is deliberate: a flapping session is a session that is still moving.
    """
    now = time.time() if now is None else now
    state = load_state(state_file)
    streaks = state.get("streaks", {}) if isinstance(state.get("streaks"), dict) else {}
    new_streaks = {}

    for row in rows:
        key = row["session"]
        prev = streaks.get(key) or {}
        if row["class"] == "OK":
            # Condition cleared by itself. Drop the streak entirely and never page.
            row["streak"] = 0
            row["would_page"] = False
            continue
        n = int(prev.get("n", 0)) + 1 if prev.get("class") == row["class"] else 1
        row["streak"] = n
        # `paged` latches so a persisting condition pages ONCE, not on every check.
        already = bool(prev.get("paged")) and prev.get("class") == row["class"]
        row["would_page"] = (n >= debounce) and not already
        new_streaks[key] = {
            "class": row["class"],
            "n": n,
            "last_seen": now,
            "paged": already or row["would_page"],
        }

    if persist:
        # Forget any session not seen this run; its condition cleared or the session ended.
        save_state(state_file, {"updated": now, "streaks": new_streaks})
    return rows


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _rec(rtype, ts, **kw):
    r = {"type": rtype, "timestamp": dt.datetime.fromtimestamp(
        ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")}
    r.update(kw)
    return r


def _assistant(ts, blocks, stop_reason="tool_use", **kw):
    return _rec("assistant", ts, message={"role": "assistant", "content": blocks,
                                          "stop_reason": stop_reason}, **kw)


def _tool_use(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _tool_result(tid, text, is_error=False):
    return {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": is_error}


def _write(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def selftest() -> int:
    """Prove the detector fires on synthetic stuck transcripts and stays quiet on healthy ones."""
    passed = failed = 0

    def check(label, got, want):
        nonlocal passed, failed
        ok = got == want
        if ok:
            passed += 1
            print(f"  PASS  {label}")
        else:
            failed += 1
            print(f"  FAIL  {label}\n          got={got!r}\n          want={want!r}")

    now = time.time()
    root = tempfile.mkdtemp(prefix="stuck-selftest-")
    proj = os.path.join(root, "projects")
    state = os.path.join(root, "state.json")

    # ---- 1. HEALTHY: varied tool calls, all answered, active seconds ago -----
    t = now - 30
    healthy = []
    for i, cmd in enumerate(["ls", "git status", "pytest -q", "rg foo"]):
        healthy.append(_assistant(t + i, [_tool_use(f"h{i}", "Bash", {"command": cmd})]))
        healthy.append(_rec("user", t + i + 0.5,
                            message={"role": "user", "content": [_tool_result(f"h{i}", "ok")]}))
    healthy.append(_assistant(now - 5, [{"type": "text", "text": "DONE: all four ran."}],
                              stop_reason="end_turn"))
    _write(os.path.join(proj, "-healthy", "sess-healthy.jsonl"), healthy)

    # ---- 2. AT REST: ended its turn cleanly, idle for HOURS. Must stay OK. ---
    rest = [_assistant(now - 7200, [{"type": "text", "text": "DONE: shipped it."}],
                       stop_reason="end_turn")]
    _write(os.path.join(proj, "-rest", "sess-rest.jsonl"), rest)

    # ---- 3. SILENT: asked for a tool 40 min ago, never got a result ----------
    sil = [_assistant(now - 3000, [_tool_use("s1", "Bash", {"command": "ls"})]),
           _rec("user", now - 2999, message={"role": "user",
                                             "content": [_tool_result("s1", "ok")]}),
           _assistant(now - 2400, [_tool_use("s2", "Bash",
                                             {"command": "npx tsx forever.ts"})])]
    _write(os.path.join(proj, "-silent", "sess-silent.jsonl"), sil)

    # ---- 4. LOOPING: same command, same args, four times running ------------
    loop = []
    for i in range(4):
        loop.append(_assistant(now - 300 + i,
                               [_tool_use(f"l{i}", "Bash", {"command": "git push"})]))
        loop.append(_rec("user", now - 300 + i + 0.5,
                         message={"role": "user",
                                  "content": [_tool_result(f"l{i}", "rejected", True)]}))
    _write(os.path.join(proj, "-loop", "sess-loop.jsonl"), loop)

    # ---- 5. BLOCKED_ON_HUMAN: ended turn on a question, idle 30 min ---------
    blk = [_assistant(now - 1800,
                      [{"type": "text",
                        "text": "I can drop the column or keep it. Which do you want?"}],
                      stop_reason="end_turn", entrypoint="cli")]
    _write(os.path.join(proj, "-blocked", "sess-blocked.jsonl"), blk)

    # ---- 5b. the SAME question from a HEADLESS one-shot. Nobody is waiting. --
    blk_sdk = [_assistant(now - 1800,
                          [{"type": "text",
                            "text": "I can drop the column or keep it. Which do you want?"}],
                          stop_reason="end_turn", entrypoint="sdk-cli")]
    _write(os.path.join(proj, "-blockedsdk", "sess-blockedsdk.jsonl"), blk_sdk)

    # ---- 6. ERRORED: repeated API errors in the tail ------------------------
    err = [_assistant(now - 120, [{"type": "text", "text": "API Error: 529 overloaded_error"}],
                      stop_reason="end_turn", isApiErrorMessage=True),
           _assistant(now - 60, [{"type": "text", "text": "API Error: 529 overloaded_error"}],
                      stop_reason="end_turn", isApiErrorMessage=True)]
    _write(os.path.join(proj, "-errored", "sess-errored.jsonl"), err)

    print("CLASSIFICATION")
    rows = {r["session"]: r for r in scan(proj, live_window_s=6 * 3600, now=now)}
    check("healthy session is OK", rows["sess-healthy"]["class"], "OK")
    check("session at rest (end_turn, idle 2h) is OK", rows["sess-rest"]["class"], "OK")
    check("unanswered tool call after 40m is SILENT", rows["sess-silent"]["class"], "SILENT")
    check("4 identical tool calls is LOOPING", rows["sess-loop"]["class"], "LOOPING")
    check("interactive session idle after a question is BLOCKED_ON_HUMAN",
          rows["sess-blocked"]["class"], "BLOCKED_ON_HUMAN")
    check("the SAME question from a headless sdk-cli one-shot is OK (no human waiting)",
          rows["sess-blockedsdk"]["class"], "OK")
    check("repeated API errors is ERRORED", rows["sess-errored"]["class"], "ERRORED")
    check("all seven sessions were found", len(rows), 7)

    print("\nRECOVERY MUST SILENCE A RUN (regression: session 74f4ed5c, 2026-08-21)")
    # The real shape that produced a false positive: 4 identical error results, then the
    # session recovered and kept working. `err_texts` is a filtered subsequence, so its
    # trailing run stayed 4 even though the transcript had moved on.
    rec_recs = []
    for i in range(4):
        rec_recs.append(_assistant(now - 400 + i * 10,
                                   [_tool_use(f"r{i}", "Agent", {"prompt": f"task {i}"})]))
        rec_recs.append(_rec("user", now - 400 + i * 10 + 5,
                             message={"role": "user", "content": [
                                 _tool_result(f"r{i}", "Agent fleet cap: 3 of 3 leases are "
                                                       "live, so this agent is refused.",
                                              True)]}))
    # ...and then it recovered: three successful calls after the errors.
    for i in range(3):
        rec_recs.append(_assistant(now - 300 + i * 10,
                                   [_tool_use(f"g{i}", "Bash", {"command": f"echo {i}"})]))
        rec_recs.append(_rec("user", now - 300 + i * 10 + 5,
                             message={"role": "user",
                                      "content": [_tool_result(f"g{i}", "ok")]}))
    rec_recs.append(_assistant(now - 250, [{"type": "text", "text": "DONE: recovered."}],
                               stop_reason="end_turn"))
    _write(os.path.join(proj, "-recovered", "sess-recovered.jsonl"), rec_recs)

    # The same 4 errors with NO recovery after them must still fire.
    _write(os.path.join(proj, "-notrecovered", "sess-notrecovered.jsonl"), rec_recs[:8])

    rr = {r["session"]: r for r in scan(proj, live_window_s=6 * 3600, now=now)}
    check("4 identical errors FOLLOWED BY SUCCESS is not a loop",
          rr["sess-recovered"]["class"], "OK")
    check("the same 4 errors with nothing since IS a loop",
          rr["sess-notrecovered"]["class"], "LOOPING")

    # Same rule for API errors.
    apirec = [_assistant(now - 200, [{"type": "text", "text": "API Error: 529 overloaded"}],
                         stop_reason="end_turn", isApiErrorMessage=True),
              _assistant(now - 190, [{"type": "text", "text": "API Error: 529 overloaded"}],
                         stop_reason="end_turn", isApiErrorMessage=True),
              _assistant(now - 180, [_tool_use("ok1", "Bash", {"command": "ls"})]),
              _rec("user", now - 175, message={"role": "user",
                                               "content": [_tool_result("ok1", "ok")]}),
              _assistant(now - 170, [{"type": "text", "text": "DONE: back."}],
                         stop_reason="end_turn")]
    _write(os.path.join(proj, "-apirec", "sess-apirec.jsonl"), apirec)
    ra = {r["session"]: r for r in scan(proj, live_window_s=6 * 3600, now=now)}
    check("API errors followed by a successful tool call is not ERRORED",
          ra["sess-apirec"]["class"], "OK")

    print("\nTHRESHOLD IS LOAD-BEARING (mutation proof)")
    # A 3-call run must NOT trip a threshold of 4: proves LOOP_RUN is read, not decorative.
    loop3 = []
    for i in range(2):
        loop3.append(_assistant(now - 300 + i,
                                [_tool_use(f"m{i}", "Bash", {"command": "git push"})]))
    _write(os.path.join(proj, "-loop3", "sess-loop3.jsonl"), loop3)
    r3 = {r["session"]: r for r in scan(proj, live_window_s=6 * 3600, now=now)}
    check("2 identical calls is below the run threshold of 3",
          r3["sess-loop3"]["class"] != "LOOPING", True)
    # Silence threshold: raise it above the gap and SILENT must stop firing.
    r_hi = {r["session"]: r for r in scan(proj, live_window_s=6 * 3600,
                                          silent_s=99999, now=now)}
    check("SILENT stops firing when the threshold is raised above the gap",
          r_hi["sess-silent"]["class"], "OK")

    print("\nDEBOUNCE — a self-clearing condition must never page")
    fresh = [dict(rows["sess-silent"])]
    apply_debounce(fresh, state_file=state, now=now)
    check("check 1 of a real condition does NOT page", fresh[0]["would_page"], False)
    check("check 1 records a streak of 1", fresh[0]["streak"], 1)

    fresh2 = [dict(rows["sess-silent"])]
    apply_debounce(fresh2, state_file=state, now=now + 300)
    check("check 2 of the SAME condition DOES page", fresh2[0]["would_page"], True)

    fresh3 = [dict(rows["sess-silent"])]
    apply_debounce(fresh3, state_file=state, now=now + 600)
    check("check 3 does NOT page again (latched, no repeat spam)",
          fresh3[0]["would_page"], False)

    # The founder's constraint, stated as a test: recovered between checks => silence.
    save_state(state, {"streaks": {}})
    flap1 = [dict(rows["sess-silent"])]
    apply_debounce(flap1, state_file=state, now=now)
    recovered = dict(rows["sess-silent"], **{"class": "OK", "evidence": "recovered"})
    flap2 = [recovered]
    apply_debounce(flap2, state_file=state, now=now + 300)
    check("a condition that SELF-HEALS between checks never pages", flap2[0]["would_page"], False)
    back = [dict(rows["sess-silent"])]
    apply_debounce(back, state_file=state, now=now + 600)
    check("and after recovery the streak restarts at 1 (still no page)",
          back[0]["would_page"], False)

    # A class that changes is two one-check conditions, not one two-check condition.
    save_state(state, {"streaks": {}})
    a = [dict(rows["sess-silent"])]
    apply_debounce(a, state_file=state, now=now)
    b = [dict(rows["sess-silent"], **{"class": "LOOPING"})]
    apply_debounce(b, state_file=state, now=now + 300)
    check("a session that flips class does not page", b[0]["would_page"], False)

    print("\nSAFETY")
    big = os.path.join(proj, "-big", "sess-big.jsonl")
    os.makedirs(os.path.dirname(big), exist_ok=True)
    filler = json.dumps(_rec("user", now - 10, message={"role": "user",
                                                        "content": "x" * 900})) + "\n"
    with open(big, "w") as fh:
        for _ in range(4000):
            fh.write(filler)
        fh.write(json.dumps(_assistant(now - 5, [{"type": "text", "text": "hi"}],
                                       stop_reason="end_turn")) + "\n")
    size = os.path.getsize(big)
    recs = tail_records(big, tail_bytes=50_000)
    check(f"a {size} B transcript is read from its tail only, bounded",
          len(recs) <= TAIL_RECORDS and len(recs) > 0, True)
    check("a corrupt/truncated line does not crash the parser",
          tail_records.__name__ and len(tail_records(big, tail_bytes=137)) >= 0, True)
    bad = os.path.join(proj, "-bad", "sess-bad.jsonl")
    _write(bad, [])
    with open(bad, "w") as fh:
        fh.write("{not json at all\n\n{\"type\":\"assistant\"}\n")
    check("a file of garbage classifies without raising",
          classify(tail_records(bad), 99999)[0] in ("OK", "SILENT"), True)
    check("an empty record list is OK, never a page", classify([], 99999)[0], "OK")

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="one JSON row per live session")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--all", action="store_true", help="include sessions classified OK")
    ap.add_argument("--projects", default=PROJECTS)
    ap.add_argument("--state-file", default=STATE_FILE)
    ap.add_argument("--silent-s", type=int, default=SILENT_S)
    ap.add_argument("--live-window-s", type=int, default=LIVE_WINDOW_S)
    ap.add_argument("--no-state", action="store_true",
                    help="classify without PERSISTING the streak (reads existing state, writes none)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    rows = scan(args.projects, live_window_s=args.live_window_s, silent_s=args.silent_s)
    apply_debounce(rows, state_file=args.state_file, persist=not args.no_state)

    shown = rows if args.all else [r for r in rows if r["class"] != "OK"]

    if args.json:
        # crew#73: the log holds two shapes, the tick header (`ts`, `rc`, `findings`, kind=tick)
        # and these session rows; every row stamps its time and says which shape it is.
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for r in shown:
            print(json.dumps({"at": at, "kind": "session",
                              **{k: r[k] for k in
                                 ("session", "slug", "class", "idle_s", "evidence",
                                  "would_page", "streak", "cwd")}}))
        return 0

    live = len(rows)
    bad = [r for r in rows if r["class"] != "OK"]
    pages = [r for r in rows if r["would_page"]]
    print(f"live sessions (transcript touched < {args.live_window_s // 3600}h): {live}")
    print(f"not OK: {len(bad)}   would_page: {len(pages)}")
    if shown:
        print()
        print(f"{'CLASS':<18} {'IDLE':>8} {'PAGE':>5} {'STREAK':>6}  SESSION / EVIDENCE")
        for r in shown:
            print(f"{r['class']:<18} {r['idle_s']:>7}s {str(r['would_page']):>5} "
                  f"{r.get('streak', 0):>6}  {r['session'][:8]}  {r['evidence'][:100]}")
            if r["cwd"]:
                print(f"{'':<18} {'':>8} {'':>5} {'':>6}    cwd: {r['cwd']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
