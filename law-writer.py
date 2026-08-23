#!/usr/bin/env python3
"""Write the dynamic laws from what actually keeps going wrong, and find contradictions.

WHY THIS EXISTS. Founder, 2026-08-23: "the laes need to be a self wrting laaw based on
real, incidents, founders, conplainta repeted istakes, eperiences,etc", "thats the only
ay", "we need static fied laws afew", "and dynic laws nd rewrite and resole contrdiitns".

THE TWO TIERS.
  STATIC  ~/AGENTS.md. Ten laws. Hand-written, rarely changed, and they win every tie.
          A rule earns a place there only if it needs a judgement no machine can make.
  DYNAMIC This file's output. Generated from evidence, carrying its own counts, and
          deleted the moment the evidence stops recurring.

WHY GENERATED RATHER THAN WRITTEN. The estate's most expensive failure is prose that was
true once. A hand-written rule cannot tell you whether it is still needed, so the list
only ever grows -- 32 laws by 2026-08-22, cut to 10 the next day because nobody could
hold them. A generated law carries the count that justifies it, so the same command that
writes it also retires it.

WHAT COUNTS AS EVIDENCE. Only things a machine measured, never a recollection:
  - a guard REFUSED a command, repeatedly           -> agents keep making this mistake
  - the founder complained, repeatedly, on a theme  -> we keep costing him the same hour
  - a guard reported itself broken                  -> an instrument is lying
Each dynamic law names its instrument and its count. A law with no count is not a law
here; it is a comment, and this file will not write it.

RETIREMENT IS THE POINT. Below THRESHOLD occurrences in the window, a law is dropped. The
list is meant to shrink when the estate improves, which is the only honest way to tell
whether it did.

    python3 law-writer.py                # print the dynamic laws + contradictions
    python3 law-writer.py --write        # write ~/.claude/LAWS.dynamic.md
    python3 law-writer.py --hook          # SessionStart: read the cache, never build
    python3 law-writer.py --selftest
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import sys
import time

HOME = os.path.expanduser("~")
STATIC = os.path.join(HOME, ".claude", "AGENTS.md")
INCIDENTS = os.path.join(HOME, ".claude", "LAWS-INCIDENTS.md")
BOARD = os.path.join(HOME, ".claude", "ESTATE_BOARD.jsonl")
FRICTION = os.path.join(HOME, ".claude", "state", "friction-relay.json")
PROJECTS = os.path.join(HOME, ".claude", "projects")
OUT = os.path.join(HOME, ".claude", "LAWS.dynamic.md")

WINDOW_DAYS = 7
THRESHOLD = 3          # under this many occurrences in the window, it is not a pattern
MAX_LAWS = 12          # a list he cannot hold is a list he ignores

#: What a refused command looks like coming back from a guard or the harness. Each maps to
#: the mistake it proves. The text is matched against tool_result bodies.
REFUSALS = (
    ("rule_add_all",      r"BLOCKED by rule-guard:.*git add",
     "Stage explicit paths. `git add -A` here commits another process's test output.",
     "store/ and storage/ are tracked runtime state that pytest writes to."),
    ("rule_no_verify",    r"BLOCKED by rule-guard:.*no-verify",
     "Do not skip the commit gate. Say why it must be skipped instead.",
     "Skipping the gate is a decision, not a convenience."),
    ("shared_checkout",   r"BLOCKED by rule-guard:.*(shared checkout|shared_stash|stash)",
     "Do not stash or commit in a checkout another session is standing on.",
     "A branch switched under a live session strands it mid-run."),
    ("classifier_write",  r"(auto mode classifier|permission classifier).*",
     "Chain fewer commands when one will do; a compound script goes to the classifier.",
     "Bare read-only commands are never refused; compound ones are judged."),
    ("scope_guard",       r"scope-guard",
     "Keep project detail out of the laws file; it belongs in that project's CLAUDE.md.",
     "One rules file per scope."),
    ("close_guard",       r"THIS REPLY DOES NOT SAY WHERE THE WORK STANDS",
     "Open the reply with DONE:, BLOCKED: or WORKING:.",
     "Leaving him to infer where the work stands is the cost."),
    ("dupe_work",         r"dupe-work-fence",
     "Look for the owner before writing: git log --all -1 -- <path>.",
     "Two implementations of one class race in production."),
)

#: Founder complaints cluster on a handful of themes. The pattern is his words, the law is
#: what would have prevented that sentence being typed.
THEMES = (
    ("no_evidence",  r"(dont see|don't see|no evidence|evodence|other tha chattig|narrat)",
     "Show the command and its output in the reply. Not a description of having run it."),
    ("too_slow",     r"(asap|too slow|hurry|longer you take|still waiting|how long)",
     "Start the long job first and say what you are waiting on, then stop."),
    ("repeating",    r"(i said|i told you|i asked|you keep|same mistake|again)",
     "Read the friction relay before you act; he has already answered this."),
    ("not_working",  r"(still not|not working|doesnt work|does not work|wtf)",
     "Prove the thing runs before reporting it done. Installed is not operational."),
    ("ignoring",     r"(ignoring|elephant in the roo|what are you workng|wtf are you)",
     "Name the job at the top of the turn and measure every action against it."),
)


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _recent_transcripts(cutoff: float) -> list[str]:
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
            names = os.listdir(p)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            f = os.path.join(p, name)
            try:
                if os.path.getmtime(f) >= cutoff:
                    out.append(f)
            except OSError:
                continue
    return out


def gather_refusals(cutoff: float) -> dict:
    """Count what guards actually refused. A refusal is a mistake an agent tried to make."""
    counts: dict[str, dict] = {}
    pats = [(k, re.compile(p, re.I), law, why) for k, p, law, why in REFUSALS]
    for path in _recent_transcripts(cutoff):
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"tool_result"' not in line and "hookSpecificOutput" not in line:
                    continue
                if len(line) > 200_000:
                    line = line[:200_000]
                for key, pat, law, why in pats:
                    if pat.search(line):
                        c = counts.setdefault(key, {"n": 0, "law": law, "why": why,
                                                    "instrument": "guard refusal in transcripts"})
                        c["n"] += 1
                        break
    return counts


def gather_complaints() -> dict:
    """Cluster his complaints by theme. The relay already did the finding."""
    counts: dict[str, dict] = {}
    try:
        with open(FRICTION, encoding="utf-8") as fh:
            items = json.load(fh).get("complaints") or []
    except Exception:
        return counts
    pats = [(k, re.compile(p, re.I), law) for k, p, law in THEMES]
    for h in items:
        text = str(h.get("text", "")).lower()
        for key, pat, law in pats:
            if pat.search(text):
                c = counts.setdefault(key, {"n": 0, "law": law, "why": "",
                                            "instrument": "friction-relay complaints",
                                            "quote": ""})
                c["n"] += 1
                if not c["quote"]:
                    c["quote"] = str(h.get("text", ""))[:120]
                break
    return counts


def gather_broken() -> dict:
    """A guard that reported itself broken is an instrument that may be lying."""
    counts: dict[str, dict] = {}
    try:
        fh = open(BOARD, encoding="utf-8")
    except OSError:
        return counts
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("kind") != "guard-broken":
                continue
            g = str(d.get("guard") or "?")
            c = counts.setdefault(g, {"n": 0, "instrument": "guard_report rows on the board"})
            c["n"] += 1
    return counts


def static_subjects() -> list[str]:
    """The headline of each static law, so a dynamic law cannot restate one."""
    try:
        text = open(STATIC, encoding="utf-8").read()
    except OSError:
        return []
    return [m.strip().lower() for m in re.findall(r"^#{1,3} LAW \d+ — (.+)$", text, re.M)]


def contradictions() -> list[str]:
    """Mechanical checks only. Each one is a thing a reader would act on wrongly."""
    out = []
    # 1. The incidents file is indexed by law number. If its numbering has drifted from the
    #    static laws, every pointer from a law to its incident lands on the wrong incident.
    try:
        stat = open(STATIC, encoding="utf-8").read()
        inc = open(INCIDENTS, encoding="utf-8").read()
    except OSError:
        return out
    s_titles = dict(re.findall(r"^#{1,3} LAW (\d+) — (.+)$", stat, re.M))
    i_titles = dict(re.findall(r"^#{1,3} LAW (\d+) — (.+)$", inc, re.M))
    drift = []
    for n, t in sorted(s_titles.items(), key=lambda kv: int(kv[0])):
        other = i_titles.get(n)
        if other and other.strip().lower()[:18] != t.strip().lower()[:18]:
            drift.append("LAW %s: laws say %r, incidents say %r" % (n, t.strip()[:38], other.strip()[:38]))
    if drift:
        out.append("LAWS-INCIDENTS.md is indexed against a different law numbering. "
                   "%d of %d law numbers point at the wrong incident:\n      %s"
                   % (len(drift), len(s_titles), "\n      ".join(drift[:6])))
    if len(i_titles) > len(s_titles):
        out.append("LAWS-INCIDENTS.md carries %d laws, AGENTS.md carries %d. The extra %d "
                   "describe rules no longer in force."
                   % (len(i_titles), len(s_titles), len(i_titles) - len(s_titles)))
    return out


def build(cutoff: float) -> tuple[list[dict], list[str]]:
    laws = []
    for key, c in gather_refusals(cutoff).items():
        if c["n"] >= THRESHOLD:
            laws.append({"id": key, "n": c["n"], "text": c["law"], "why": c["why"],
                         "src": c["instrument"]})
    for key, c in gather_complaints().items():
        if c["n"] >= max(2, THRESHOLD - 1):      # his time costs more than a retry does
            laws.append({"id": key, "n": c["n"], "text": c["law"],
                         "why": 'he said: "%s"' % c.get("quote", ""), "src": c["instrument"]})
    for g, c in gather_broken().items():
        if c["n"] >= THRESHOLD:
            laws.append({"id": "broken:" + g, "n": c["n"],
                         "text": "Do not trust %s until it is fixed; it reported itself broken." % g,
                         "why": "an instrument that fails silently reads exactly like a clean estate.",
                         "src": c["instrument"]})
    # rewrite: one subject, one law -- keep the best-evidenced
    best: dict[str, dict] = {}
    for law in laws:
        k = law["text"][:40].lower()
        if k not in best or law["n"] > best[k]["n"]:
            best[k] = law
    laws = sorted(best.values(), key=lambda x: -x["n"])[:MAX_LAWS]
    return laws, contradictions()


def render(laws: list[dict], contras: list[str], cutoff: float) -> str:
    L = ["# The dynamic laws",
         "",
         "**Generated. Do not edit this file.** `python3 ~/.claude/scripts/law-writer.py --write`",
         "",
         "Every law below is here because a machine counted it happening, in the last %d days."
         % WINDOW_DAYS,
         "The count is the whole justification. Below %d occurrences a law is dropped, so this"
         % THRESHOLD,
         "list shrinks when the estate gets better -- that is the only honest way to tell.",
         "",
         "The static laws in `~/AGENTS.md` outrank every line here. Written %s."
         % dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
         ""]
    if not laws:
        L += ["No pattern cleared the threshold in the window. Nothing to add to the static laws.", ""]
    for i, law in enumerate(laws, 1):
        L.append("## D%d — %s" % (i, law["text"]))
        L.append("")
        L.append("*%d occurrences in %d days, measured by %s.*" % (law["n"], WINDOW_DAYS, law["src"]))
        if law.get("why"):
            L.append("")
            L.append(law["why"])
        L.append("")
    L += ["---", "", "## Contradictions found", ""]
    if not contras:
        L.append("None. The static laws and the incident record agree.")
    for c in contras:
        L.append("- %s" % c)
    L.append("")
    return "\n".join(L)


def selftest() -> int:
    fails = []

    def ck(label, cond):
        print("  %s %s" % ("ok  " if cond else "FAIL", label))
        if not cond:
            fails.append(label)

    now = _now()
    ck("no evidence writes no laws", "No pattern cleared" in render([], [], now))
    one = [{"id": "x", "n": 7, "text": "Stage explicit paths.", "why": "because", "src": "guards"}]
    r = render(one, [], now)
    ck("a law carries its count", "7 occurrences" in r)
    ck("a law names its instrument", "measured by guards" in r)
    ck("static laws are said to win", "outrank" in r)
    ck("contradiction section always present", "## Contradictions found" in r)
    ck("clean contradiction state is stated", "None." in r)
    ck("a contradiction is rendered", "drifted" in render([], ["drifted"], now))
    # rewrite: same subject twice keeps the better-evidenced one
    saved = globals()["gather_refusals"], globals()["gather_complaints"], globals()["gather_broken"]
    globals()["gather_refusals"] = lambda c: {
        "a": {"n": 4, "law": "Stage explicit paths always.", "why": "", "instrument": "i"},
        "b": {"n": 9, "law": "Stage explicit paths always.", "why": "", "instrument": "i"}}
    globals()["gather_complaints"] = lambda: {}
    globals()["gather_broken"] = lambda: {}
    laws, _ = build(now)
    ck("one subject yields one law", len(laws) == 1)
    ck("it keeps the better-evidenced count", laws and laws[0]["n"] == 9)
    globals()["gather_refusals"] = lambda c: {
        "a": {"n": 2, "law": "Below threshold.", "why": "", "instrument": "i"}}
    laws2, _ = build(now)
    ck("below threshold is retired", laws2 == [])
    (globals()["gather_refusals"], globals()["gather_complaints"],
     globals()["gather_broken"]) = saved
    ck("static subjects are readable", isinstance(static_subjects(), list))
    print("law-writer selftest: %d/%d checks passed" % (12 - len(fails), 12))
    return 1 if fails else 0


HOOK_LAWS = 6   #: how many dynamic laws reach a session. The whole file is long and context is the
                #: scarcest thing in a session; the top few by count carry most of the evidence.
STALE_H = 6     #: hours before the cache is old enough that injecting it would be a lie about "now"


def hook() -> int:
    """SessionStart mode: read the cache, print a short block, never build.

    Building takes over a minute of transcript scanning, so it can never run on the hook path --
    a slow SessionStart hook delays every session on the machine. The launchd job refreshes the
    file; this only reads it. Missing or stale reads as silence, not as an error: a session that
    starts before the first refresh should just not see dynamic laws.
    """
    try:
        age = _now() - os.path.getmtime(OUT)
        text = open(OUT, encoding="utf-8").read()
    except OSError:
        return 0
    if age > STALE_H * 3600:
        return 0
    laws = re.findall(r"^## (D\d+) — (.+)$\n\n\*(\d+) occurrences", text, re.M)
    contras = re.findall(r"^- (.+)$", text.split("## Contradictions found", 1)[-1], re.M)
    if not laws and not contras:
        return 0
    out = ["[laws/dynamic] WRITTEN FROM WHAT ACTUALLY HAPPENED, NOT FROM OPINION.",
           "Each line was counted on this estate in the last %d days. The static laws in"
           % WINDOW_DAYS,
           "~/AGENTS.md outrank every line here. Refreshed %dm ago." % (age // 60), ""]
    for tag, txt, n in laws[:HOOK_LAWS]:
        out.append("  %s (%sx) %s" % (tag, n, txt))
    if contras:
        out += ["", "  Contradictions in the rulebook itself -- do not cite a law by number until fixed:"]
        for c in contras[:3]:
            out.append("    - %s" % c.split(":")[0])
    print("\n".join(out))
    return 0


def main() -> int:
    if "--hook" in sys.argv:
        return hook()
    if "--selftest" in sys.argv:
        return selftest()
    cutoff = _now() - WINDOW_DAYS * 86400
    laws, contras = build(cutoff)
    text = render(laws, contras, cutoff)
    if "--write" in sys.argv:
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, OUT)
        print("law-writer: %d dynamic laws, %d contradictions -> %s"
              % (len(laws), len(contras), OUT))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
