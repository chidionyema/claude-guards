#!/usr/bin/env python3
"""context-guard-hook.py v2 — UserPromptSubmit guard against MARATHON SESSIONS.

v1 watched resident context only (250K/400K thresholds). Obsolete: with
CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000 the context is capped — sessions no longer
die fat, they die LONG. Measured 2026-06-10 (7d): two ~14,000-turn, ~3-day sessions
= 91% of all weekly cost at a modest ~88K median resident context.

v2.1 (2026-08-06) RETUNED against measured data. Audit of 37 prospector sessions
(`token-audit.py -Users-chidionyema`): $374.64 / 4,183 requests = $0.0896 per request,
near-constant; cost drivers cache_read 55.6% + cache_write 23.3% = 79% context
transport, output only 21.1%. Peaks cluster at 160-167K (the 200K auto-compact knee)
and only 1 of 37 sessions ever reached 170K — so the old RESIDENT_HARD=170_000 fired
about ONCE in 37 sessions and the resident "strong" path was effectively dead. Warn
130_000 -> 85_000 (the measured mean-of-medians), hard 170_000 -> 140_000 (under the
knee, so it can actually fire). Beware: peak CAN exceed the window (max seen 277,374)
when one turn dumps a lot before compaction triggers.

v2 watches session SHAPE — user-prompt count, transcript size, session age, and
resident context — and when the shape goes marathon it injects an instruction that
tells Claude to (a) write a handoff to checkpoints/LATEST.md and (b) hand the user a
one-keystroke /clear. This is loss-proof: memory-loop.py (SessionStart hook) re-injects
checkpoints/LATEST.md into the next fresh session automatically.

Per-session state lives next to the transcript: <session>.jsonl.guard.json
Cost when it fires: ~70 tokens of injected context. Silent otherwise. Never blocks.
"""
import json, os, sys, time

RESIDENT_WARN = 85_000             # tokens re-billed every turn (= measured mean-of-medians)
RESIDENT_HARD = 140_000            # BELOW the ~167K compaction knee, so it can actually fire
PROMPTS_WARN  = 25                 # user prompts in one session ≈ a task boundary passed
SIZE_WARN     = 20 * 1024 * 1024   # transcript bytes ≈ proxy for turn count
AGE_WARN      = 8 * 3600           # seconds; marathons ran ~3 days
RENUDGE_EVERY = 10                 # min prompts between nudges (no spam)
TAIL          = 200_000            # bytes of transcript scanned for resident ctx


def tail_text(path, n=TAIL):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > n:
                fh.seek(size - n)
                fh.readline()
            return fh.read().decode("utf-8", "replace")
    except Exception:
        return ""


def resident(path):
    r = 0
    for line in tail_text(path).splitlines():
        if '"usage"' not in line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("type") != "assistant":
            continue
        u = (rec.get("message") or {}).get("usage") or {}
        if u:
            r = (u.get("input_tokens", 0) or 0) + (u.get("cache_read_input_tokens", 0) or 0) \
                + (u.get("cache_creation_input_tokens", 0) or 0)
    return r


def load_state(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return {"first_seen": time.time(), "prompts": 0, "last_nudge_prompt": 0}


def save_state(path, st):
    try:
        with open(path, "w") as fh:
            json.dump(st, fh)
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    path = data.get("transcript_path") or ""
    if not path:
        sys.exit(0)

    state_path = path + ".guard.json"
    st = load_state(state_path)
    st["prompts"] = st.get("prompts", 0) + 1
    save_state(state_path, st)

    prompts = st["prompts"]
    if prompts - st.get("last_nudge_prompt", 0) < RENUDGE_EVERY and st.get("last_nudge_prompt", 0) > 0:
        sys.exit(0)  # rate-limit: already nudged recently

    r = resident(path)
    try:
        size = os.path.getsize(path)
    except Exception:
        size = 0
    age = time.time() - st.get("first_seen", time.time())

    signals = []
    if r >= RESIDENT_WARN:
        signals.append(f"~{r/1000:.0f}K resident context re-billed every turn")
    if prompts >= PROMPTS_WARN:
        signals.append(f"{prompts} prompts this session")
    if size >= SIZE_WARN:
        signals.append(f"{size/1024/1024:.0f}MB transcript (high turn count)")
    if age >= AGE_WARN:
        signals.append(f"session is {age/3600:.0f}h old")

    strong = (r >= RESIDENT_HARD or prompts >= 2 * PROMPTS_WARN
              or size >= 2 * SIZE_WARN or age >= 24 * 3600)
    if not signals or (len(signals) < 2 and not strong):
        sys.exit(0)  # healthy shape — stay silent

    st["last_nudge_prompt"] = prompts
    save_state(state_path, st)

    ckpt = os.path.join(os.path.dirname(path), "checkpoints", "LATEST.md")
    if strong:
        msg = (f"[session-guard] MARATHON SHAPE: {'; '.join(signals)}. "
               f"Claude: finish the current step only, then (1) write a concise handoff "
               f"(task+goal, decisions, files touched, exact next steps) to {ckpt} and "
               f"(2) end your reply with the single line: \"Safe point — type /clear "
               f"(state saved, nothing will be lost)\". The memory-loop hook auto-restores "
               f"that handoff in the next session. Do this without asking.")
    else:
        msg = (f"[session-guard] Session going long ({'; '.join(signals)}). Claude: at the "
               f"next task boundary, write a handoff to {ckpt} and tell the user: "
               f"\"Safe point — type /clear (state saved)\". Loss-proof via memory-loop.")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": msg,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
