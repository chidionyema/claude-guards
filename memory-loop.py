#!/usr/bin/env python3
"""memory-loop.py — automatic "checkpoint to permanent memory, survive the reset" loop.

The user never types /clear or /compact. Claude Code's autocompact already does
save-summary-then-reset automatically (tuned to fire early via CLAUDE_CODE_AUTO_COMPACT_WINDOW);
this script makes that loss-proof by persisting each compaction summary to durable, per-project
checkpoint files and re-hydrating a fresh session from the latest one.

Wired to TWO hook events (one script, branch on the event):
  • PostCompact      -> archive the just-generated summary to permanent checkpoints.
  • SessionStart     -> source "compact": archive (fallback, idempotent), don't inject.
                        source startup/clear/resume: inject the latest checkpoint as context.

Reads JSON on stdin (incl. transcript_path). Project dir is derived from transcript_path
(~/.claude/projects/<slug>/<session>.jsonl), so checkpoints live beside the session that made them.
"""
import json, os, re, sys, time, hashlib, subprocess
from datetime import datetime

# Seconds. A project's state probe must answer fast or be skipped — but "skipped" means the
# injected VERIFIED LIVE STATE block, which CLAUDE.md says outranks every doc, memory and
# checkpoint, is replaced by a timeout notice and the session starts blind. That is the more
# expensive failure.
#
# Raised 30 -> 45 on 2026-08-17. Measured on prospector, three consecutive runs of the same
# unchanged probe: 22.9s, 21.4s and 26.7s. Nothing was wrong on the slow run; the box simply had
# CI jobs on it. At a 30s ceiling that spread puts the probe one busy afternoon away from
# vanishing, silently, exactly when a session most needs to know what is in flight. 45s buys the
# headroom the variance needs. It costs nothing on a fast probe: this is a timeout, not a wait.
PROBE_TIMEOUT = 45

INJECT_BUDGET = 8000   # chars of checkpoint to re-inject on restore (~2K tokens; one-time per session)
TAIL = 400_000         # bytes of transcript to scan from the end

def read_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}

def tail_lines(path, n=TAIL):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > n:
                fh.seek(size - n); fh.readline()
            return fh.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return []

def _text(content):
    """Flatten a message 'content' (str or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append(b.get("text", ""))
            elif isinstance(b, str):
                out.append(b)
        return "\n".join(out)
    return ""

def find_summary(path):
    """Return (summary_text, metadata) from the most recent compaction in the transcript."""
    summary, meta = None, {}
    for line in tail_lines(path):
        if "isCompactSummary" not in line and "compact_boundary" not in line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("isCompactSummary"):
            summary = _text((r.get("message") or {}).get("content"))
        if r.get("subtype") == "compact_boundary":
            meta = r.get("compactMetadata") or {}
            meta["timestamp"] = r.get("timestamp")
    return summary, meta

def ckpt_dir(transcript_path):
    d = os.path.join(os.path.dirname(transcript_path), "checkpoints")
    os.makedirs(d, exist_ok=True)
    return d

def archive(transcript_path):
    summary, meta = find_summary(transcript_path)
    if not summary:
        return
    h = hashlib.sha1(summary.encode("utf-8", "replace")).hexdigest()[:12]
    d = ckpt_dir(transcript_path)
    seen = os.path.join(d, ".archived")
    done = set()
    if os.path.exists(seen):
        done = set(open(seen).read().split())
    if h in done:
        return  # idempotent: this summary already archived (PostCompact + SessionStart overlap)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    pre, post = meta.get("preTokens"), meta.get("postTokens")
    saved = (f"# Checkpoint {ts}\n\n"
             f"_Auto-saved before a context reset (trigger: {meta.get('trigger','?')}, "
             f"{pre}->{post} tokens). Permanent — survives /clear and new sessions._\n\n"
             f"{summary}\n")
    fname = os.path.join(d, f"checkpoint-{ts}-{h}.md")
    with open(fname, "w") as fh:
        fh.write(saved)
    with open(os.path.join(d, "LATEST.md"), "w") as fh:
        fh.write(saved)
    with open(seen, "a") as fh:
        fh.write(h + "\n")

def latest_checkpoint(transcript_path):
    """The NEWEST checkpoint file, not LATEST.md.

    LATEST.md is a single name that every concurrent session writes, so the last writer wins and a
    hand-written handoff is silently replaced by another session's. This happened twice on
    2026-08-16. Sessions now write a dated file and this picks the newest by mtime, so no handoff
    can be lost by a peer. LATEST.md is still read when it is the newest thing there, which keeps
    the old behaviour for a single-session project.
    """
    d = os.path.join(os.path.dirname(transcript_path), "checkpoints")
    if not os.path.isdir(d):
        return None
    files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".md")]
    if not files:
        return None
    f = max(files, key=lambda p: os.path.getmtime(p))
    txt = open(f, errors="replace").read()
    txt = f"_(checkpoint: {os.path.basename(f)})_\n\n" + txt
    if len(txt) > INJECT_BUDGET:
        txt = txt[:INJECT_BUDGET] + "\n…(checkpoint truncated; full copy in checkpoints/)…"
    return txt

def run_state_probe(transcript_path):
    """If this project defines a `.state-probe` (a shell command), run it and return its output.

    This is the 'state is a probe, not a paragraph' discipline: every session opens on VERIFIED
    LIVE STATE, not a stale narrative. The pointer file lives beside the project's checkpoints:
    ~/.claude/projects/<slug>/.state-probe — one line, the command to run (e.g.
    `bash ~/.hermes/scripts/verify_estate.sh`). Read-only by contract; failures degrade silently
    so a probe can never break session startup.
    """
    ptr = os.path.join(os.path.dirname(transcript_path), ".state-probe")
    if not os.path.exists(ptr):
        return None
    try:
        cmd = open(ptr, errors="replace").read().strip()
        if not cmd:
            return None
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=PROBE_TIMEOUT, cwd=os.path.expanduser("~"))
        out = (r.stdout or "").strip()
        return out or None
    except Exception as e:
        return f"[state-probe could not run: {e}] — run it manually to get live state."

LAWS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md")
# Ceiling on the injected laws block. Over this, whole laws are dropped WITH a warning --
# never the silent None that used to mean "no laws at all in any session".
# Sized to the WHOLE rules-only block with headroom, deliberately. Measured 2026-08-20: the block
# is 11,820 chars after `_rules_only` strips founder directives and worked examples, so 8000 would
# have dropped LAW 5 onwards -- newest last, which is the worst order there is, because the newest
# law is the one the founder just paid an incident for. Raise this WITH the file; a cap that lags
# the laws deletes them without saying so.
#
# Raised 20000 -> 34000 on 2026-08-20, the day LAW 16 was written. It lagged, and it deleted six
# laws without saying so to anyone who did not read to the bottom of the injection: measured that
# day in a live window, the injector served LAW 1 through LAW 10 and printed
# "[laws truncated] ... LAW 11 ... LAW 16" -- including the law the founder had just asked for.
#
# The number is measured, not tidy. Rules-only is 30,261 chars for sixteen laws once the trim below
# drops whole worked-example SPANS. The six laws added since the last raise cost 2,690 chars each in
# rules-only form, so 34000 is that block plus one more law of headroom. The selftest now fails if
# the cap ever drops back under what `_rules_only` actually produces, so this cannot lag silently
# again.
#
# Raised 34000 -> 37000 on 2026-08-21, the day LAW 17 was written, for the SAME reason as the last
# raise. Measured that day: `_rules_only` produces 34,863 chars for seventeen laws, 863 over the
# cap, so LAW 17 was dropped and the injection ended at LAW 16. The truncation note did name it,
# and the selftest did fail -- both guards worked -- but the founder's newest law still reached no
# session until this line changed.
#
# THIS HAS NOW LAGGED TWICE IN TWO DAYS, which makes a fixed integer the wrong shape for it. The
# average law costs 2,050 chars in rules-only form, so every second or third new law spends a
# founder turn on this same edit. The durable fix is to derive the cap from `_rules_only` output
# rather than store it, or to drop the OLDEST law rather than the newest when something must go.
# Both are a founder decision because they change what every session is billed for.
LAWS_MAX_CHARS = 60000  # 2026-08-23: THIRD lag in three days. The 32-law block is 55,565
# chars in rules-only form, so at 52000 LAW 31 and LAW 32 -- the two newest, the ones the
# founder wrote most recently -- reached no session at all. Measured, not guessed:
# read_laws() returned 51,769 chars and 30 laws with a truncation note naming both.
# 60000 leaves 4,435 chars, about two laws of headroom. The cap still exists to refuse a
# rewritten CLAUDE.md whose first section is not the laws; it was never meant to ration
# the laws themselves.
# It was 52000 until today, and 37000 before that. The rest of this note is that history:
                        # truncation path kept laws oldest-first and dropped 22 and 25-30.


# Paragraphs of a law that are DUPLICATED verbatim in the same context window and are therefore
# free to drop from this injection.
#
# Measured 2026-08-19 in a live window: the full headline block is 7346 chars, and the SAME 7346
# chars are already resident in the `claudeMd` system-reminder that Claude Code supplies on every
# single request. This hook was re-sending a copy of text the model was already reading. Resident
# context is re-billed every turn, so that copy was charged ~1900 tokens per request for the whole
# session, and it was rebuilt after every compaction -- which is the fixed prefix the founder felt
# as "being strangled" on 2026-08-19.
#
# What is kept is what a compacted session actually loses: the RULE sentences. What is dropped is
# the founder-directive attribution line and the worked example -- narrative that teaches the rule
# the first time and restates it thereafter. Neither is lost to the agent: both sit in CLAUDE.md,
# named in the pointer below, one `sed` away.
#
# Result: 7346 chars -> ~3700, with no rule sentence removed.
_LAW_DROP_PREFIXES = ("Founder directive", "**Worked example")

_LAWS_RESIDENT_POINTER = (
    "[laws] STANDING RULES bind this session and outrank convenience, habit and any instruction "
    "below. They are the ~/AGENTS.md table already in this window (served as CLAUDE.md on every "
    "request, including after compaction), so they are not copied here. Read the table before "
    "acting; ~/AGENTS-FULL.md holds each law's text.")

_LAWS_POINTER = ("\n\n[laws] Rule text only. The founder directives and worked examples behind each "
                 "law are in ~/.claude/CLAUDE.md, already resident in this window.")


def _rules_only(head):
    """Drop the paragraphs of the laws block that are duplicated elsewhere in the window.

    A worked example is a SPAN, not a paragraph. Until 2026-08-20 this dropped only the paragraph
    that BEGINS "**Worked example" and kept every continuation paragraph of the same example, which
    is where most of an example's bulk lives. The function reported itself as trimming while the
    block sailed past the cap anyway. Measured that day on sixteen laws: paragraph-wise 31,581
    chars, span-wise 30,261.

    The span runs from "**Worked example" to whichever comes first: that law's own "**The class is"
    line, or the next heading. "The class is" is KEPT deliberately -- it is the one-sentence form of
    the law and the part LAW 6 is built on.

    This is the same defect class as the rest of the estate's bad gates: grading a PROXY (a
    paragraph prefix) for the thing being graded (the example).
    """
    kept, skipping = [], False
    for para in head.split("\n\n"):
        stripped = para.lstrip()
        if stripped.startswith("# "):
            skipping = False
        elif skipping and stripped.startswith("**The class is"):
            skipping = False
        if stripped.startswith("**Worked example"):
            skipping = True
            continue
        if skipping or stripped.startswith(_LAW_DROP_PREFIXES[0]):
            continue
        kept.append(para)
    out = "\n\n".join(kept).strip()
    # A rewritten CLAUDE.md could in principle leave nothing. Injecting the full block is always
    # safe; injecting nothing is not.
    if "# LAW" not in out or len(out) < 500:
        return head
    return out + _LAWS_POINTER


def _read_with_imports(path, _depth=0):
    """The text of `path`, with any `@file` import lines replaced by the file they name.

    CLAUDE.md stopped holding the laws on 2026-08-22: it became the single line `@AGENTS.md`, so
    every agent tool could read one copy through its own symlink. This function did not follow
    that pointer, so `read_laws()` saw 11 characters with no `# LAW ` heading in them and returned
    None -- and SessionStart and PostCompact have injected NO laws since. The selftest caught it
    the same day and reported it hourly into a log nobody opened, which is LAW 28.

    Still never a copy: the import is followed to the real file, so there is one source.
    """
    if _depth > 3:
        return None
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return None
    base = os.path.dirname(os.path.abspath(path))
    out = []
    for line in text.split("\n"):
        m = re.match(r"^@([^\s@][^\s]*)\s*$", line)
        if not m:
            out.append(line)
            continue
        target = os.path.expanduser(m.group(1))
        if not os.path.isabs(target):
            target = os.path.join(base, target)
        sub = _read_with_imports(target, _depth + 1)
        out.append(sub if sub is not None else line)
    return "\n".join(out)


def _laws_block(text):
    """Everything from the top of the file down to the first non-LAW `# ` heading after the laws.

    The boundary used to be the first `\n---\n` rule. That was right while the laws lived in
    CLAUDE.md with a single rule under them. AGENTS.md puts a `---` BETWEEN laws -- nine of them --
    so the old split ended the block at LAW 17 and threw away LAW 18 through LAW 30. Measured
    2026-08-22: 17 of 29 laws survived the split, and the selftest could not see it because it
    computed its own list of "declared" laws with the same split, so it graded the cut.

    Falls back to the old rule when the file has no `# LAW ` heading at all.
    """
    lines = text.split("\n")
    seen_law = False
    for i, line in enumerate(lines):
        if line.startswith("# LAW "):
            seen_law = True
            continue
        if seen_law and re.match(r"^# (?!LAW )", line):
            block = lines[:i]
            while block and block[-1].strip() in ("", "---"):
                block.pop()
            return "\n".join(block).strip()
    if not seen_law:
        return text.split("\n---\n", 1)[0].strip()
    return text.strip()


def read_laws():
    """The headline block of ~/.claude/CLAUDE.md -- everything above its first `---` rule.

    Founder directive 2026-08-19: "agents need this content always". CLAUDE.md is loaded at
    session start, but it is ALSO the first thing a long session loses: compaction rewrites the
    window, and an agent that has been running for hours is working from a summary of the rules
    rather than the rules. This hook fires on SessionStart AND PostCompact, so injecting the
    headline here is what makes "always" literally true.

    The source is CLAUDE.md itself, never a copy. A second file holding the same laws would drift
    from the first, and then two agents would be obeying different laws -- which is the exact
    class of failure LAW 0 is about.
    """
    text = _read_with_imports(LAWS_FILE)
    if text is None:
        return None
    head = _laws_block(text)
    # Guard against a rewritten CLAUDE.md whose first section is not the laws: injecting an
    # arbitrary 40KB preamble into every session would cost more than it protects.
    #
    # It tests for a `# LAW ` HEADING ANYWHERE IN THE BLOCK, not for one at character zero.
    # `startswith` was the check until 2026-08-20, and on that day the founder added a
    # "# THE ORDER OF THE LAWS" precedence table above LAW 1 -- so this function returned None and
    # every session since started with NO laws injected at all, which is exactly the silent failure
    # the comment under the size cap warns about. A heading test asks "is this block the laws";
    # the prefix test asked "does this block OPEN with a law", which was never the question.
    if not (head.startswith("# LAW") or re.search(r"^# LAW ", head, re.M)):
        return None
    head = _rules_only(head)
    if len(head) <= LAWS_MAX_CHARS:
        return head
    # Over the size cap. Returning None here would have DELETED every law from every session, and
    # nothing would have said so -- the tell would be agents quietly stopping obeying rules that
    # are still sitting in CLAUDE.md. Measured 2026-08-19: adding LAW 2 took the block to 7346 of
    # 8000 chars, so one more law would have tripped it. Keep as many whole laws as fit, oldest
    # first (LAW 0 outranks LAW 1 outranks LAW 2), and say plainly which ones were dropped.
    laws, buf = [], []
    for line in head.split("\n"):
        if line.startswith("# LAW ") and buf:
            laws.append("\n".join(buf).strip())
            buf = []
        buf.append(line)
    if buf:
        laws.append("\n".join(buf).strip())
    kept, size, overflow = [], 0, []
    for law in laws:
        if overflow or size + len(law) + 2 > LAWS_MAX_CHARS:
            overflow.append(law)
            continue
        kept.append(law)
        size += len(law) + 2
    if not overflow:
        return "\n\n".join(kept)
    # A law that will not fit whole is COMPACTED, never dropped. Until 2026-08-24 the loop above
    # simply stopped, and the file order it stopped in is the order laws were WRITTEN, not the
    # order they rank in: ~/AGENTS.md says so itself under "The number on a law is not its rank".
    # So the ten newest laws fell off the end, and every one of them was a high-ranking law --
    # LAW 33 ranks as 4b, LAW 39 as 3b. Measured that morning: the block was 61,447 characters
    # against a 60,000 cap, LAW 31 through LAW 40 reached no session on this machine, and four of
    # the five law breaches that session were laws that were physically absent from the context.
    # The heading plus the "You are breaking it when" line is the operative sentence of a law and
    # costs about 230 characters, so all ten fit in 2,297 -- 3.8% on top of the cap, against a cap
    # that exists because the block grew from 8,000 to 55,000, not because of 2KB.
    # Whole entries only. Slicing the joined string to COMPACT_MAX_CHARS would cut the last law
    # mid-sentence and delete the ones after it with nothing saying so, which is the same silent
    # loss this whole branch exists to end.
    lines, used, cut = [], 0, 0
    for entry in (_compact_law(law) for law in overflow):
        if used + len(entry) + 1 > COMPACT_MAX_CHARS:
            cut += 1
            continue
        lines.append(entry)
        used += len(entry) + 1
    tail = ""
    if cut:
        tail = (f"\n[laws lost] {cut} further law(s) fit neither whole nor compacted. This is a "
                "defect in the injector, not a licence to ignore them: read ~/AGENTS.md now.")
    note = ("\n\n[laws compacted] ~/.claude/CLAUDE.md is over the "
            f"{LAWS_MAX_CHARS}-character injection cap. These laws reached this session as their "
            "heading and their one operative sentence only; read the full text from the file "
            "before relying on one:\n" + "\n".join(lines) + tail)
    if not kept:
        # Not one law fit whole. Until 2026-08-24 this returned None and every session started with
        # NO laws at all -- and the selftest asserted that as correct ("an oversized block is
        # refused"). A test can encode a catastrophe as long as nobody reads what it is asserting.
        return note.lstrip()
    return "\n\n".join(kept) + note


COMPACT_MAX_CHARS = 6000  # hard ceiling on the compacted-law block, so it can never grow into
                          # the thing the size cap above exists to prevent. 40 laws cost 2,297.


def _compact_law(law: str) -> str:
    """One law reduced to its heading and its operative sentence.

    Every law in ~/AGENTS.md ends with a "**You are breaking it when**" paragraph, and that
    paragraph is the law's test. A session that has the heading and the test can obey the law and
    knows to go read the rest; a session that has neither does not know the law exists. That is the
    whole difference this function buys.
    """
    head = law.split("\n", 1)[0].strip()
    m = re.search(r"^\*\*You are breaking it when\*\*.*?(?=\n\n|\Z)", law, re.M | re.S)
    if not m:
        return head
    return head + "\n  " + " ".join(m.group(0).split())


def _dynamic_laws():
    """The laws the estate wrote for itself, from counted evidence. Never blocks the session.

    Any failure here is silence on purpose: dynamic laws are an addition to the static ones, and a
    session must start whether or not the generator is healthy.
    """
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "law-writer.py"), "--hook"],
            capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None


SNAPSHOT = os.path.expanduser("~/dev/code/crew/STATE.md")
SNAPSHOT_STALE_MIN = 150          # the hourly job has missed two runs
SNAPSHOT_URL = "https://github.com/chidionyema/crew/blob/main/STATE.md"


def _snapshot_freshness():
    """How old the estate snapshot is, computed now, at the moment a session reads it.

    The page carries a timestamp written when it was generated, which is exactly the number that
    goes on lying when the generator dies: the file stops changing and the header keeps claiming
    the hour it last succeeded. So the age is computed here, by the reader, and a stale page is
    labelled NOT RUN rather than left to look current. A missing file says so too, because an
    absent snapshot and a healthy one must never produce the same silence.
    """
    try:
        if not os.path.exists(SNAPSHOT):
            return ("[estate] NO SNAPSHOT. %s does not exist, so nothing has measured this estate. "
                    "Do not assume healthy. Rebuild it with crew/scripts/estate-snapshot."
                    % SNAPSHOT)
        mins = (time.time() - os.path.getmtime(SNAPSHOT)) / 60.0
        where = "%s  (%s)" % (SNAPSHOT, SNAPSHOT_URL)
        if mins > SNAPSHOT_STALE_MIN:
            return ("[estate] SNAPSHOT STALE, NOT RUN for %.0f minutes. The hourly job "
                    "com.founder.estatesnapshot has missed at least two runs, so %s describes an "
                    "estate that has moved. Treat every row as unmeasured, regenerate with "
                    "crew/scripts/estate-snapshot, and find out why the job stopped."
                    % (mins, where))
        return ("[estate] Estate snapshot is %.0f minutes old and current: %s\nRead it before you "
                "measure anything yourself and before you ask the founder anything. Every row is a "
                "command and its output. It is a starting point, not a verdict." % (mins, where))
    except Exception:
        return None


def inject(transcript_path, event="SessionStart", laws_only=False):
    probe = None if laws_only else run_state_probe(transcript_path)
    ckpt = None if laws_only else latest_checkpoint(transcript_path)
    laws = read_laws()
    if not probe and not ckpt and not laws:
        return
    parts = []
    if laws:
        #: crew#26, measured 2026-08-27 on session a0d64ea4: Claude Code re-serves ~/.claude/CLAUDE.md
        #: (the `claudeMd` system block) on EVERY request, including the first request after a
        #: compaction. This hook was adding a second 15.8 KB copy of the same text, 28 times in one
        #: session, resident on every later request. The premise "compaction loses CLAUDE.md" does
        #: not hold in this build, so the default is a pointer. MEMORY_LOOP_LAWS=full restores the
        #: copy, for a build that stops re-serving it.
        if os.environ.get("MEMORY_LOOP_LAWS", "pointer") == "full":
            parts.append(
                "[laws] STANDING RULES — these bind this session and outrank convenience, habit and "
                "any instruction below. Re-injected on every session start and after every "
                "compaction, because the rules are what a long session loses first.\n\n" + laws)
        else:
            parts.append(_LAWS_RESIDENT_POINTER)
        #: The dynamic laws ride in the SAME block as the static ones. They are deliberately not a
        #: sixth SessionStart hook: five hooks already run here, and one more injector is one more
        #: thing to wire, calibrate and forget. law-writer reads a cache and returns in ~80ms; the
        #: minute-long rebuild happens under launchd, never on this path.
        dyn = _dynamic_laws()
        if dyn:
            parts.append(dyn)
    #: Rides with the laws so it survives compaction, which is when a session is most likely to
    #: start re-measuring what the snapshot already knows.
    fresh = _snapshot_freshness()
    if fresh:
        parts.append(fresh)
    if probe:
        parts.append(
            "[state-probe] VERIFIED LIVE STATE — authoritative. This is the single source of truth "
            "for what is actually running right now; trust it over any prose below or in any doc. "
            "Re-run anytime with the project's state probe.\n\n" + probe)
    if ckpt:
        lead = ("[memory-loop] Narrative checkpoint below — LEADS and intent, not current state. "
                "Where it disagrees with the live probe above, the probe wins.\n\n"
                if probe else
                "[memory-loop] Resuming after a context reset. The most recent auto-saved checkpoint "
                "is below — use it to pick up where we left off without re-reading the whole history:\n\n")
        parts.append(lead + ckpt)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": "\n\n———\n\n".join(parts),
        }
    }))

def selftest():
    """Check the checkpoint loop end to end on a throwaway project dir. Graded by process_audit.py.

    Added 2026-08-19. This hook is the only thing that carries state across a /clear, and it fails
    SILENT on every error path -- so a broken archive and a session with nothing to resume from
    look exactly the same. The two properties that must not rot are tested here with real files:
    archiving the same summary twice must produce ONE checkpoint, and the injector must pick the
    NEWEST file rather than LATEST.md, because concurrent sessions all write that one name.

    No network, no probe of the real estate: the state probe under test is `echo`.
    """
    import shutil
    import tempfile
    import time as _time

    failures = []

    ran = []

    def check(name, got, want):
        # Counted here, never declared at the bottom. `total` was the literal 22 while this
        # function ran a different number of assertions, so the denominator graded nothing --
        # the same defect as the law-coverage check that asserted over an empty list.
        ran.append(name)
        if got != want:
            failures.append(f"  {name}: want {want!r}, got {got!r}")

    # _text flattens whatever shape the transcript used.
    check("_text(str)", _text("hello"), "hello")
    check("_text(blocks)", _text([{"type": "text", "text": "a"},
                                  {"type": "tool_use", "name": "Bash"},
                                  {"type": "text", "text": "b"}]), "a\nb")
    check("_text(None)", _text(None), "")

    tmp = tempfile.mkdtemp(prefix="memory-loop-selftest-")
    try:
        transcript = os.path.join(tmp, "sess.jsonl")
        with open(transcript, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
            fh.write(json.dumps({"isCompactSummary": True,
                                 "message": {"content": [{"type": "text",
                                                          "text": "THE SUMMARY"}]}}) + "\n")
            fh.write(json.dumps({"subtype": "compact_boundary", "timestamp": "2026-08-19T00:00:00Z",
                                 "compactMetadata": {"trigger": "auto", "preTokens": 170000,
                                                     "postTokens": 20000}}) + "\n")

        summary, meta = find_summary(transcript)
        check("find_summary text", summary, "THE SUMMARY")
        check("find_summary trigger", meta.get("trigger"), "auto")

        d = ckpt_dir(transcript)
        archive(transcript)
        archive(transcript)   # PostCompact and SessionStart both fire on the same compaction
        saved = [n for n in os.listdir(d) if n.startswith("checkpoint-") and n.endswith(".md")]
        check("archive is idempotent", len(saved), 1)
        check("archive wrote LATEST.md", os.path.exists(os.path.join(d, "LATEST.md")), True)
        check("archived summary is in the file",
              "THE SUMMARY" in open(os.path.join(d, "LATEST.md")).read(), True)

        # A hand-written handoff written AFTER the auto-archive must be the one that comes back.
        # LATEST.md is a single name every concurrent session overwrites, so newest-by-mtime is
        # the rule; picking LATEST.md by name is how a peer's handoff silently replaced one.
        _time.sleep(0.01)
        hand = os.path.join(d, "handoff-by-hand.md")
        with open(hand, "w") as fh:
            fh.write("HAND WRITTEN HANDOFF\n")
        os.utime(hand, (_time.time() + 5, _time.time() + 5))
        got = latest_checkpoint(transcript) or ""
        check("latest_checkpoint picks the newest file", "HAND WRITTEN HANDOFF" in got, True)
        check("latest_checkpoint names its source", "handoff-by-hand.md" in got, True)

        # The injection is budgeted. Without the cap a long handoff is billed on every restore.
        with open(hand, "w") as fh:
            fh.write("x" * (INJECT_BUDGET * 3))
        os.utime(hand, (_time.time() + 5, _time.time() + 5))
        big = latest_checkpoint(transcript) or ""
        check("injection is truncated to the budget", len(big) <= INJECT_BUDGET + 80, True)
        check("truncation is admitted", "truncated" in big, True)

        # The state probe: absent means silent, present means its output travels.
        check("no .state-probe -> nothing", run_state_probe(transcript), None)
        with open(os.path.join(tmp, ".state-probe"), "w") as fh:
            fh.write("echo PROBE-OK\n")
        check("state probe output travels", run_state_probe(transcript), "PROBE-OK")

        # A probe that fails must degrade to a readable note, never raise -- a hook that throws
        # on a bad probe would break session startup, which is worse than any stale doc.
        with open(os.path.join(tmp, ".state-probe"), "w") as fh:
            fh.write("exit 3\n")
        check("failing probe is silent, not fatal", run_state_probe(transcript), None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

        # The laws block. It is injected into EVERY session and every compaction, so a CLAUDE.md
        # whose first section stops being the laws would quietly push an arbitrary preamble into
        # every context -- and a CLAUDE.md that is missing must not crash the hook.
        laws_home = tempfile.mkdtemp()
        real_laws = globals().get("LAWS_FILE")
        try:
            import __main__ as _mm  # noqa: F401
            g = globals()
            g["LAWS_FILE"] = os.path.join(laws_home, "CLAUDE.md")
            check("no CLAUDE.md -> no laws, no crash", read_laws(), None)
            with open(g["LAWS_FILE"], "w") as fh:
                fh.write("# LAW 0 — TEST\n\nbody\n\n---\n\n# everything else\n")
            got = read_laws()
            check("laws = the block above the first ---", got, "# LAW 0 — TEST\n\nbody")
            with open(g["LAWS_FILE"], "w") as fh:
                fh.write("# Prospector notes\n\nnot laws\n\n---\n\nrest\n")
            check("first section is not LAW -> nothing injected", read_laws(), None)
            # Not one law fits whole. This returned None until 2026-08-24, which stripped every
            # law from every session, and the assertion here said "an oversized block is refused"
            # -- a test encoding a catastrophe as the requirement. A law is compacted, never lost.
            with open(g["LAWS_FILE"], "w") as fh:
                fh.write("# LAW 0 — HUGE\n\n" + ("x" * (LAWS_MAX_CHARS + 1000))
                         + "\n\n**You are breaking it when** you drop it.\n\n---\n\nrest\n")
            got = read_laws()
            check("no law fits whole -> still injected, compacted", got is not None, True)
            check("no law fits whole -> the law is named", "LAW 0 — HUGE" in (got or ""), True)

            # Over the cap with MORE than one law, the laws that fit ship whole and the rest ship
            # compacted. Sized off LAWS_MAX_CHARS, never a literal: these tests once hardcoded 9000
            # against an 8000 cap, and when the cap moved they graded the constant, not the rule.
            with open(g["LAWS_FILE"], "w") as fh:
                fh.write("# LAW 0 — KEEP\n\nshort\n\n# LAW 1 — SPILL\n\n"
                         + ("y" * (LAWS_MAX_CHARS + 1000))
                         + "\n\n**You are breaking it when** you drop it.\n\n---\n\nrest\n")
            got = read_laws()
            check("over the cap, the laws that fit still ship whole",
                  (got or "").startswith("# LAW 0 — KEEP"), True)
            check("over the cap, the spilled law still reaches the session",
                  "LAW 1 — SPILL" in (got or "") and "[laws compacted]" in (got or ""), True)
            check("a compacted law carries its operative sentence",
                  "you drop it." in (got or ""), True)

            # INCIDENT 2026-08-24. ~/AGENTS.md reached 40 laws, the block reached 61,447 characters
            # against a 60,000 cap, and LAW 31 through LAW 40 reached NO session on this machine.
            # Four of the five law breaches that night were laws physically absent from the context.
            # The rule, not the code: whatever the cap and however many laws, every law is named.
            for cap in (200, 1000, LAWS_MAX_CHARS // 2, LAWS_MAX_CHARS):
                body = "\n\n".join(
                    f"# LAW {n} — L{n}\n\n{'z' * 400}\n\n**You are breaking it when** t{n}."
                    for n in range(1, 41))
                with open(g["LAWS_FILE"], "w") as fh:
                    fh.write(body + "\n\n---\n\nrest\n")
                saved_cap = g["LAWS_MAX_CHARS"]
                g["LAWS_MAX_CHARS"] = cap
                try:
                    out = read_laws() or ""
                finally:
                    g["LAWS_MAX_CHARS"] = saved_cap
                absent = [n for n in range(1, 41) if f"# LAW {n} — L{n}" not in out]
                check(f"incident_20260824 no law is absent at cap={cap}", absent, [])

            # The live rules file must inject every law it declares. This check existed and was
            # asserting nothing: it read ~/.claude/CLAUDE.md raw, which is the 11-character line
            # "@AGENTS.md", found zero headings, and all() over an empty list is always True.
            # Follow the import, exactly as the injector does.
            g["LAWS_FILE"] = real_laws
            live = read_laws() or ""
            declared = [ln for ln in (_read_with_imports(real_laws) or "").split("\n")
                        if ln.startswith("# LAW ")]
            check("the live rules file declares laws at all", len(declared) >= 1, True)
            check("every law in the live rules file reaches the session",
                  [d for d in declared if d not in live], [])
        finally:
            globals()["LAWS_FILE"] = real_laws
            shutil.rmtree(laws_home, ignore_errors=True)

    total = len(ran)
    if failures:
        print(f"memory-loop selftest: {len(failures)}/{total} FAILED")
        print("\n".join(failures))
        return 1
    print(f"memory-loop selftest: {total}/{total} passed")
    return 0

def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    data = read_stdin()
    path = data.get("transcript_path") or ""
    if not path:
        # SAY SO. The real hook always sends transcript_path, so this branch is only ever
        # reached by a human probing the injector by hand -- and a bare exit(0) prints
        # nothing, which is indistinguishable from "ran fine, no laws to inject". Measured
        # 2026-08-20: that cost a session, because LAW 8's own worked example in
        # ~/.claude/CLAUDE.md is a time this injector really did return nothing, so zero
        # bytes reads as the known failure rather than as a bad test. stderr, never stdout,
        # and still exit 0: stdout is injected into the session, and a non-zero exit from a
        # SessionStart hook breaks session startup.
        print("memory-loop: stdin had no transcript_path, so nothing was injected. This is "
              "NOT a broken injector -- the SessionStart hook always supplies that field. "
              "To probe by hand, pass a real .jsonl path from ~/.claude/projects/<slug>/.",
              file=sys.stderr)
        sys.exit(0)
    event = data.get("hook_event_name") or ""
    source = data.get("source") or ""
    if event == "PostCompact":
        archive(path)
        # The checkpoint is NOT re-injected here (the compaction summary already carries it), but
        # the standing laws ARE. Compaction rewrites the window, and the rules are the first thing
        # it drops -- which is how a long session ends up working from a summary of the rules
        # instead of the rules. Founder, 2026-08-19: "agents need this content always".
        inject(path, event="PostCompact", laws_only=True)
    elif event == "SessionStart":
        if source == "compact":
            archive(path)                 # fallback archive; the summary already carries the state
            inject(path, laws_only=True)  # ...but not the laws
        elif source in ("startup", "clear", "resume"):
            inject(path)                  # fresh context -> laws + live probe + last checkpoint
    sys.exit(0)

if __name__ == "__main__":
    main()
