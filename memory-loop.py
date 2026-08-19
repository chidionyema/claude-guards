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
import json, os, sys, hashlib, subprocess
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

def inject(transcript_path):
    probe = run_state_probe(transcript_path)
    ckpt = latest_checkpoint(transcript_path)
    if not probe and not ckpt:
        return
    parts = []
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
            "hookEventName": "SessionStart",
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

    def check(name, got, want):
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

    total = 15
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
        sys.exit(0)
    event = data.get("hook_event_name") or ""
    source = data.get("source") or ""
    if event == "PostCompact":
        archive(path)
    elif event == "SessionStart":
        if source == "compact":
            archive(path)                 # fallback archive; do not re-inject (summary already in context)
        elif source in ("startup", "clear", "resume"):
            inject(path)                  # fresh context -> re-hydrate from the last checkpoint
    sys.exit(0)

if __name__ == "__main__":
    main()
