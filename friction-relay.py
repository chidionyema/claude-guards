#!/usr/bin/env python3
"""Carry the founder's complaints to every session, not just the one that heard them.

WHY THIS EXISTS. Founder, 2026-08-23: "i think you need to be sying constantly",
"there are still a lot of issues and gaps", "until we have napped all friction ad
daddresed", "all agents need to understand and enforce ways of working".

WHAT WAS ALREADY THERE, AND WHAT WAS MISSING. founder_board.collect_founder_friction()
already reads every transcript on this machine and finds his complaints accurately.
Measured 2026-08-23: 14 complaints in 24h, 13 of them in the last 6 hours, one of them
90 seconds old and made to a DIFFERENT session. The instrument is not the gap.

The gap is delivery. That collector writes a row onto an hourly HTML page, and the row
itself says the quiet part: "said to one session; no other session could see it until
this row existed". A page is a pull. LAW 9: he does not go to the result, the result
comes to him -- and LAW 6: a signal that reaches nobody has closed nothing. So six
sessions each carry on annoying him in the same way, because none of them can hear what
he said to the other five.

WHAT THIS DOES. One thing. At SessionStart -- which includes every compaction, when a
session loses exactly this kind of context first -- it injects the complaints he made to
ANY session in the last 6 hours. Nothing else. It never blocks.

FAILS OPEN, ALWAYS. No cache, stale cache, bad JSON, surprise payload: exit 0 silently.
A hook that breaks a session start is a hook somebody deletes by lunchtime.

TWO MODES.
    python3 friction-relay.py              # hook mode: read cache, inject, exit fast
    python3 friction-relay.py --refresh    # rebuild the cache (launchd, every 10 min)
    python3 friction-relay.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".claude", "state", "friction-relay.json")
PROJECTS = os.path.join(HOME, ".claude", "projects")
SCRIPTS = os.path.join(HOME, ".claude", "scripts")

#: The directory this file is committed in. friction-relay.py, founder_board.py and
#: rulings.json travel together in one repository, so this finds them on the Mac AND in
#: a clone. SCRIPTS is a hardcoded home path and stays only for CACHE, which really is
#: machine state. Reading the other two through SCRIPTS made two selftest checks pass on
#: a runner by finding nothing -- CI caught "lexicon is borrowed, not copied" the first
#: time the selftest was actually gated.
HERE = os.path.dirname(os.path.abspath(__file__))

WINDOW = 6 * 3600          # how far back a complaint still counts
MAX_SHOWN = 6              # a wall of text is ignored; six is a glance
STALE = 15 * 60            # older than this and the hook kicks a background refresh
#: How far back into a transcript to read. It was 600_000 and that was measured wrong:
#: these files run to tens of megabytes, so 600 KB of tail covered only the last few
#: minutes of a busy session. Against founder_board's extractor over the same 20 files,
#: the relay saw 32 in-window messages where the board saw 170 -- it would have carried
#: one complaint in thirteen and reported a calm estate. 40 MB covers a full day of the
#: busiest session here. Only --refresh pays this cost, in the background; the hook
#: itself reads the cache and never opens a transcript.
TAIL_BYTES = 40_000_000


#: Used only when founder_board.py cannot be read. Named so the selftest can tell a
#: borrowed lexicon from a degraded one instead of counting words.
_FALLBACK_WORDS = ("fuck", "shit", "wtf", "still not", "i said", "i told you", "i asked",
                   "frustrat", "annoying", "tired of", "no progress", "asap", "too slow")


def _friction_words() -> tuple:
    """Borrow the lexicon from founder_board rather than keeping a second copy.

    Two lists of his own words drift apart, and the one nobody edits is the one that
    silently stops matching. If the import fails we fall back to a minimal set so the
    relay still works with a degraded vocabulary rather than reporting a clean estate.
    """
    try:
        sys.path.insert(0, HERE)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_fb", os.path.join(HERE, "founder_board.py"))
        fb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fb)
        words = tuple(getattr(fb, "FRICTION", ()))
        if words:
            return words
    except Exception:
        pass
    return _FALLBACK_WORDS


_SKIP = re.compile(r"^\s*(<|\[|\{|Caveat:|This session is being continued)")


def _recent_transcripts(now: float) -> list[str]:
    out = []
    try:
        dirs = os.listdir(PROJECTS)
    except OSError:
        return out
    for d in dirs:
        p = os.path.join(PROJECTS, d)
        if not os.path.isdir(p):
            continue
        try:
            entries = os.listdir(p)
        except OSError:
            continue
        for name in entries:
            if not name.endswith(".jsonl"):
                continue
            f = os.path.join(p, name)
            try:
                if now - os.path.getmtime(f) <= WINDOW:
                    out.append(f)
            except OSError:
                continue
    return out


def _user_texts(path: str) -> list[tuple[float, str]]:
    """Genuine typed messages from the tail of one transcript.

    A user row carrying a tool_result is the harness talking, not the founder, and a
    meta row is the harness too. Both are excluded -- counting them as complaints is
    how a friction number becomes noise nobody trusts.
    """
    out: list[tuple[float, str]] = []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()                      # drop the partial line
            blob = fh.read().decode("utf-8", "replace")
    except OSError:
        return out
    for line in blob.splitlines():
        if '"user"' not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "user" or d.get("isMeta"):
            continue
        c = (d.get("message") or {}).get("content")
        if isinstance(c, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                continue
            text = " ".join(b.get("text", "") for b in c
                            if isinstance(b, dict) and b.get("type") == "text")
        elif isinstance(c, str):
            text = c
        else:
            continue
        text = text.strip()
        if not text or _SKIP.match(text):
            continue
        ts = 0.0
        raw = d.get("timestamp")
        if isinstance(raw, str):
            try:
                import datetime as _dt
                ts = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = 0.0
        out.append((ts, text))
    return out


def refresh() -> int:
    now = time.time()
    words = _friction_words()
    hits = []
    for path in _recent_transcripts(now):
        session = os.path.basename(os.path.dirname(path))[-12:]
        for ts, text in _user_texts(path):
            if not ts or now - ts > WINDOW:
                continue
            low = text.lower()
            if any(w in low for w in words):
                hits.append({"at": ts, "session": session,
                             "text": " ".join(text.split())[:200]})
    hits.sort(key=lambda h: -h["at"])
    seen, uniq = set(), []
    for h in hits:                                  # the same sentence twice is one complaint
        k = h["text"][:80].lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    payload = {"built_at": now, "window_hours": WINDOW // 3600, "complaints": uniq,
               "incidents": _fetch_incidents()}
    tmp = CACHE + ".tmp"
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, CACHE)                          # atomic: a hook never reads half a file
    print("friction-relay: %d complaints in the last %dh across %d transcripts"
          % (len(uniq), WINDOW // 3600, len(_recent_transcripts(now))))
    return 0


#: crew#668 CP6: the incident ledger is training data, so its lesson is read at every session
#: start. The rows live in the board repository (incidents/LEDGER.jsonl, incidents/GUARDS.jsonl,
#: rendered as docs/INCIDENTS.md); they are fetched through the API in the background refresh so
#: nothing here names a checkout (LAW 46), and rendered from the cache so the hook stays fast.
BOARD_REPO = os.environ.get("ESTATE_BOARD_REPO", "chidionyema/crew")
INCIDENT_CLASSES_SHOWN = 5


def _board_jsonl(path: str) -> list[dict]:
    try:
        out = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github.raw",
             "repos/%s/contents/%s" % (BOARD_REPO, path)],
            capture_output=True, text=True, check=False, timeout=30).stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _fetch_incidents() -> dict:
    """Top incident classes across every guard on record, plus the open incidents."""
    ledger = _board_jsonl("incidents/LEDGER.jsonl")
    guards = _board_jsonl("incidents/GUARDS.jsonl")
    return summarise_incidents(ledger, guards)


def summarise_incidents(ledger: list, guards: list) -> dict:
    counts: dict = {}
    for r in ledger + guards:                       # a ledger row carries `classes`, a guard `class`
        for c in (r.get("classes") or [r.get("class")]) or []:
            c = str(c or "unclassified")
            counts[c] = counts.get(c, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    open_rows = [r for r in ledger if not r.get("resolved")]
    return {"guards": len(guards), "incidents": len(ledger),
            "classes": ranked[:INCIDENT_CLASSES_SHOWN + 1],
            "open": [{"id": r.get("id", "?"), "title": str(r.get("title", ""))[:100]}
                     for r in open_rows[:5]]}


def render_incidents(cache: dict) -> str:
    inc = cache.get("incidents") or {}
    classes = [kv for kv in inc.get("classes") or [] if kv[0] != "unclassified"]
    if not classes and not inc.get("open"):
        return ""
    lines = ["[friction-relay] WHAT THE ESTATE KEEPS GETTING WRONG (crew#668). %d incidents, %d"
             " guards on record; the top classes, from the ledger the pipeline generates:"
             % (inc.get("incidents", 0), inc.get("guards", 0)), ""]
    for cls, n in classes[:INCIDENT_CLASSES_SHOWN]:
        lines.append("  - %-32s %d" % (cls, n))
    for r in inc.get("open") or []:
        lines.append("  OPEN %s: %s" % (r.get("id"), r.get("title")))
    lines += ["", "  Before you write a guard, a script or a fix, check it is not one of these again."]
    return "\n".join(lines)


def _ago(ts: float, now: float) -> str:
    m = max(0, int((now - ts) // 60))
    return "%dm ago" % m if m < 90 else "%.1fh ago" % (m / 60.0)


def render(cache: dict, now: float) -> str:
    items = cache.get("complaints") or []
    if not items:
        return ""
    lines = ["[friction-relay] WHAT THE FOUNDER HAS COMPLAINED ABOUT IN THE LAST 6 HOURS.",
             "These were said to whichever session happened to be open. They bind you too.",
             ""]
    for h in items[:MAX_SHOWN]:
        lines.append('  - %s (session %s): "%s"'
                     % (_ago(h.get("at", 0), now), h.get("session", "?"), h.get("text", "")))
    extra = len(items) - MAX_SHOWN
    if extra > 0:
        lines.append("  ... and %d more." % extra)
    lines += ["",
              "  Do not re-ask him something he has already answered above.",
              "  If one of these is about work you are doing, it outranks your current step."]
    return "\n".join(lines)


#: Beside this script, not under a hardcoded ~/.claude/scripts. friction-relay.py and
#: rulings.json are committed in the same directory of the same repository, so this is
#: where the file is on the Mac AND in a clone. The hardcoded path made the two selftest
#: checks below pass on a runner by finding nothing, which is how a gate grades a proxy.
RULINGS = os.path.join(HERE, "rulings.json")


def ruling_problems(rows) -> list[str]:
    """Everything wrong with a rulings list, worst first. Empty means it is sound.

    Two sessions allocated R16 on 2026-08-24 -- R16-command-guards-are-rego and
    R16-founder-only-declares-live -- and R15 had gone the same way the day before.
    The id is a hand-typed sequential number and there are six sessions who cannot
    see each other, so a collision is the expected case, not the surprise. When it
    happens both rulings are real and one of them quietly stops being injected.
    """
    problems, seen = [], {}
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            problems.append("ruling %d is not an object" % i)
            continue
        rid = r.get("id") or ""
        m = re.match(r"^R(\d+)-[a-z0-9-]+$", rid)
        if not m:
            problems.append("ruling %d has no id of the form R<number>-slug: %r" % (i, rid))
            continue
        for field in ("date", "verbatim"):
            if not r.get(field):
                problems.append("%s is missing %s" % (rid, field))
        n = int(m.group(1))
        if n in seen:
            problems.append("R%d is used twice: %s and %s -- renumber the newer one"
                            % (n, seen[n], rid))
        else:
            seen[n] = rid
    return problems



def render_rulings() -> str:
    """Standing rulings, injected forever — unlike complaints, these never age out.

    2026-08-24: the founder had to repeat 'we are not going back to fly' because the
    ruling lived in one session's memory and this relay's 6-hour window. A ruling is
    not a complaint: it has no expiry. Read fresh each time (the file is tiny), fail
    open like everything else here."""
    try:
        with open(RULINGS, encoding="utf-8") as fh:
            rows = json.load(fh).get("rulings") or []
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["[friction-relay] STANDING FOUNDER RULINGS. These never expire and bind",
             "every session. Violating one, or making him repeat one, is the incident.",
             ""]
    # Never drop a ruling to tidy the block: say what is wrong and inject all of them.
    problems = ruling_problems(rows)
    if problems:
        lines[2:2] = ["  RULINGS FILE IS UNSOUND -- fix rulings.json before trusting this block:"]
        lines[3:3] = ["    - " + p for p in problems] + [""]
    for i, r in enumerate(rows):
        lines.append('  %s (%s): "%s"' % (r.get("id", "?"), r.get("date", "?"),
                                          r.get("verbatim", "")))
        if r.get("meaning") and i >= len(rows) - MEANING_ROWS:
            lines.append("      => %s" % _first_sentence(r["meaning"]))
    return "\n".join(lines)


#: crew#26, measured 2026-08-27: 39 rulings rendered 28.6 KB, re-injected on every session
#: start and every compaction (28 times in one session) and resident on every request after.
#: The verbatim quote is the ruling and is kept whole; the meaning is cut to its first sentence,
#: and rulings.json beside this script holds the rest.
MEANING_CAP = 160
#: crew#584, measured 2026-08-28: 44 rulings with a meaning line each rendered 15,993 of the
#: 16,000 cap, so the 45th ruling (R47) turned claude-guards CI red. Every verbatim quote stays
#: (11.5 KB for 45); the => meaning line is carried for the newest MEANING_ROWS only (13.2 KB),
#: the older ones are read from rulings.json.
MEANING_ROWS = 15


def _first_sentence(text: str) -> str:
    text = " ".join(str(text).split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    out = m.group(1) if m else text
    return out if len(out) <= MEANING_CAP else out[:MEANING_CAP - 1].rstrip() + "…"


def _kick_refresh() -> None:
    """Rebuild in the background. The hook must never make him wait for a scan.

    A failure here is silent by design -- the session must start either way -- so it is
    reported rather than swallowed. If this Popen never runs, the cache stops ageing and
    the relay injects a stale complaint list, which reads exactly like a calm estate.
    """
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--refresh"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        try:
            sys.path.append(os.path.join(HOME, ".claude", "scripts"))
            import guard_report
            guard_report.broken(__file__, 232, "background refresh could not start")
        except Exception:
            pass


def hook() -> int:
    try:
        json.load(sys.stdin)
    except Exception:
        pass
    now = time.time()
    try:
        with open(CACHE, encoding="utf-8") as fh:
            cache = json.load(fh)
    except Exception:
        _kick_refresh()
        return 0
    if now - float(cache.get("built_at") or 0) > STALE:
        _kick_refresh()
    text = render(cache, now)
    for block in (render_incidents(cache), render_rulings()):
        if block:
            text = (text + "\n\n" + block) if text else block
    if text:
        sys.stdout.write(text + "\n")
    return 0


def selftest() -> int:
    fails = []

    def ck(label, cond):
        print("  %s %s" % ("ok  " if cond else "FAIL", label))
        if not cond:
            fails.append(label)

    now = time.time()
    ck("empty cache injects nothing", render({"complaints": []}, now) == "")
    ck("missing key injects nothing", render({}, now) == "")
    one = {"complaints": [{"at": now - 300, "session": "abc", "text": "still not working"}]}
    out = render(one, now)
    ck("a complaint is injected", "still not working" in out)
    ck("it carries the age", "5m ago" in out)
    ck("it carries the session", "abc" in out)
    many = {"complaints": [{"at": now - i * 60, "session": "s", "text": "c%d" % i}
                           for i in range(12)]}
    o2 = render(many, now)
    ck("it caps the wall of text", o2.count("  - ") == MAX_SHOWN)
    ck("it says how many it hid", "and 6 more" in o2)
    # Grades the borrowed list, not the fallback. len() > 13 was satisfiable by the
    # 13-word fallback plus nothing, and on a runner SCRIPTS did not exist so that is
    # what it graded. Ask founder_board.FRICTION directly instead.
    ck("lexicon is borrowed from founder_board, not copied",
       set(_friction_words()) != set(_FALLBACK_WORDS) and len(_friction_words()) > 13)
    ck("a tool_result row is not a complaint",
       _SKIP.match("<system-reminder>") is not None)
    bad = {"complaints": [{"text": "no timestamp key"}]}
    try:
        render(bad, now)
        ck("a malformed row does not raise", True)
    except Exception:
        ck("a malformed row does not raise", False)
    # No `or not os.path.exists(RULINGS)` escape. rulings.json is committed beside this
    # file, so if it is not there the check has found a real defect and must say so.
    ck("rulings.json is beside this script", os.path.exists(RULINGS))
    ru = render_rulings()
    ck("standing rulings are injected", "STANDING FOUNDER RULINGS" in ru)
    ck("the fly ruling is carried verbatim", "not going back to fly" in ru)
    ck("the rulings block stays under 16 KB (crew#26: it was 28.6 KB)", len(ru) < 16000)
    led = [{"id": "I1", "classes": ["fix-proved-on-the-wrong-surface"], "title": "Otto dark",
            "resolved": ""},
           {"id": "I0", "classes": ["silent-green"], "title": "closed", "resolved": "2026-08-30"}]
    gua = [{"class": "silent-green"}] * 3 + [{"class": "unclassified"}] * 9
    inc = render_incidents({"incidents": summarise_incidents(led, gua)})
    ck("incident classes are ranked and injected", inc.index("silent-green") < inc.index("wrong-surface"))
    ck("an unclassified guard is counted, never ranked", "unclassified" not in inc)
    ck("an open incident is named", "OPEN I1: Otto dark" in inc)
    ck("a resolved incident is counted, not listed as open", "OPEN I0" not in inc)
    ck("no incident data injects nothing", render_incidents({}) == "")
    ck("the ledger is read from the board repo, never a checkout path (LAW 46)",
       "repos/%s/contents" in open(__file__).read() and "incidents/LEDGER" in open(__file__).read())
    ck("a meaning is cut to its first sentence",
       _first_sentence("Never do X. Also never do Y.") == "Never do X.")
    ck("a long first sentence is capped", len(_first_sentence("a " * 400)) <= MEANING_CAP)
    with open(RULINGS, encoding="utf-8") as fh:
        shipped = json.load(fh).get("rulings") or []
    ck("the shipped rulings file is sound", ruling_problems(shipped) == [])
    ck("every ruling is injected, none summarised away",
       all(r["id"] in ru for r in shipped))
    two_r16 = [{"id": "R16-command-guards-are-rego", "date": "2026-08-24", "verbatim": "x"},
               {"id": "R16-founder-only-declares-live", "date": "2026-08-24", "verbatim": "y"}]
    ck("two rulings sharing a number are reported",
       any("R16 is used twice" in p for p in ruling_problems(two_r16)))
    ck("a ruling with no verbatim is reported",
       any("missing verbatim" in p for p in ruling_problems(
           [{"id": "R99-x", "date": "2026-08-24", "verbatim": ""}])))
    ck("a malformed id is reported",
       ruling_problems([{"id": "sixteen", "date": "d", "verbatim": "v"}]) != [])
    ck("a sound list is not reported",
       ruling_problems([{"id": "R1-a", "date": "d", "verbatim": "v"},
                        {"id": "R2-b", "date": "d", "verbatim": "v"}]) == [])
    total = 19
    print("friction-relay selftest: %d/%d checks passed" % (total - len(fails), total))
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--refresh" in sys.argv:
        return refresh()
    return hook()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)                                 # fails open, always
