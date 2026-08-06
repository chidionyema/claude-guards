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

PROBE_TIMEOUT = 30     # seconds; a project's state probe must answer fast or be skipped

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
    d = os.path.join(os.path.dirname(transcript_path), "checkpoints")
    f = os.path.join(d, "LATEST.md")
    if not os.path.exists(f):
        return None
    txt = open(f, errors="replace").read()
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

def main():
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
