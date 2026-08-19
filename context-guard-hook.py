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
import json, os, re, sys, time

#: Above this, the PreToolUse half REFUSES context-growing calls. Same number as
#: RESIDENT_HARD on purpose: the nudge and the block must not disagree about when a
#: session is too fat, or the nudge trains you to ignore the block.
RESIDENT_BLOCK = 140_000
BLOCK_OFF = os.path.expanduser("~/.claude/state/contextguard/OFF")

#: Tools that GROW resident context. Everything not named here is allowed at any size,
#: which is the whole design: the way out of a fat session is to write the handoff and
#: commit, so Write, Edit, TodoWrite and the git half of Bash must never be refused.
_GROWING_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "Agent", "Task",
                  "NotebookRead"}

#: In auto mode reading happens through Bash (`cat`, `sed -n`, `rg`), so refusing the
#: Read tool alone would be a hole big enough to drive the session through. Only pure
#: readers are refused; git, tests, builds, redirects and the handoff write all pass.
_BASH_READER_RE = re.compile(
    r"^\s*(cat|bat|less|more|head|tail|rg|ag|ack|find|jq)\b"
    r"|^\s*grep\b|^\s*sed\s+-n\b|^\s*ls\s+-[a-zA-Z]*R")

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


PEV_DIRECTIVE = (
    "[pev] Standing workflow for implementation work this session: YOU plan, the "
    "executor implements, YOU verify.\n"
    "- Plan yourself: exact file paths, the specific edit per file, and the exact "
    "verification commands. The executor sees ONLY your plan text.\n"
    "- Dispatch mechanical/bulk implementation with the `pi_execute` MCP tool "
    "(MiniMax, cheap). Keep design, judgement and diagnosis in this session.\n"
    "- Then ALWAYS `pi_gate` (free, deterministic: typecheck/lint/tests) BEFORE any "
    "reasoning about correctness, and read the real diff — the executor's own report "
    "is a claim, not evidence.\n"
    "- Money rail / identity / contract / migrations never leave Claude Code; "
    "`pi_execute` refuses them by design. Small edits and one-liners: just do them "
    "here, a dispatch round-trip costs more than the edit."
)


def pi_bridge_registered():
    """Only advertise the workflow if the MCP server is actually configured."""
    try:
        with open(os.path.expanduser("~/.claude.json")) as fh:
            cfg = json.load(fh)
    except Exception:
        return False
    if "pi-bridge" in (cfg.get("mcpServers") or {}):
        return True
    for proj in (cfg.get("projects") or {}).values():
        if isinstance(proj, dict) and "pi-bridge" in (proj.get("mcpServers") or {}):
            return True
    return False


def save_state(path, st):
    try:
        with open(path, "w") as fh:
            json.dump(st, fh)
    except Exception:
        pass


def assess(r, prompts, size, age):
    """(signals, strong, fires) for one session shape. Pure, so it can be tested.

    Lifted out of main() on 2026-08-19 for exactly that reason: this is the whole hook -- when
    it nudges and how hard -- and nothing checked it. The hook fails OPEN, so a decision rule
    broken by a threshold edit looks identical to one that works, from inside a session.

    ONE signal is not enough on its own unless the shape is `strong`; a long session with
    nothing else wrong should not be nagged.
    """
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
    fires = bool(signals) and (len(signals) >= 2 or strong)
    return signals, strong, fires


def selftest():
    """Check the decision rule and the resident-context reader. Graded by process_audit.py."""
    import tempfile

    hour = 3600
    cases = [
        # (resident, prompts, bytes, age_s) -> (fires, strong)
        ((0, 1, 0, 0), (False, False)),                                  # fresh session
        ((RESIDENT_WARN, 1, 0, 0), (False, False)),                      # one weak signal only
        ((RESIDENT_WARN, PROMPTS_WARN, 0, 0), (True, False)),            # two weak signals
        ((RESIDENT_HARD, 1, 0, 0), (True, True)),                        # one STRONG signal
        ((0, 2 * PROMPTS_WARN, 0, 0), (True, True)),
        ((0, 0, 2 * SIZE_WARN, 0), (True, True)),
        ((0, 0, 0, 24 * hour), (True, True)),
        ((0, 0, 0, AGE_WARN), (False, False)),                           # age alone is weak
        ((RESIDENT_WARN - 1, PROMPTS_WARN - 1, 0, 0), (False, False)),   # just under both
        # The measured median session on 2026-08-19: 165K resident. Must fire STRONG.
        ((165_553, 30, 0, 2 * hour), (True, True)),
    ]
    failures = []
    for args, (want_fires, want_strong) in cases:
        _, strong, fires = assess(*args)
        if (fires, strong) != (want_fires, want_strong):
            failures.append(f"  assess{args}: want fires={want_fires} strong={want_strong}, "
                            f"got fires={fires} strong={strong}")

    # `resident` must read the LAST assistant usage block, and must sum all three input
    # counters -- reading only input_tokens under-reports a cached turn by an order of
    # magnitude, which would silence the hook exactly when it matters most.
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        fh.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "message": {"usage": {
            "input_tokens": 1, "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 3}}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "message": {"usage": {
            "input_tokens": 10, "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 1000}}}) + "\n")
        tmp = fh.name
    got = resident(tmp)
    os.unlink(tmp)
    if got != 1110:
        failures.append(f"  resident(): want 1110 (last record, all three counters), got {got}")

    # The BLOCKING half. This is the first guard here that can stop work, so both
    # directions are pinned: what it refuses, and -- more important -- what it must never
    # refuse, because those are the calls that write the handoff and get the work saved.
    under, over = RESIDENT_BLOCK - 1, RESIDENT_BLOCK
    block_cases = [
        ("Read", {}, under, False),                 # under the ceiling nothing is refused
        ("Read", {}, over, True),
        ("Grep", {}, over, True),
        ("Agent", {}, over, True),
        ("WebFetch", {}, over, True),
        ("Write", {}, over, False),                 # the handoff must always be writable
        ("Edit", {}, over, False),
        ("TodoWrite", {}, over, False),
        ("Bash", {"command": "cat foo.py"}, over, True),
        ("Bash", {"command": "rg pattern src/"}, over, True),
        ("Bash", {"command": "sed -n '1,50p' a.py"}, over, True),
        ("Bash", {"command": "grep x a.py"}, over, True),
        # Everything needed to finish and ship. If any of these ever blocks, the guard has
        # trapped the session instead of ending it.
        ("Bash", {"command": "git commit -m 'x'"}, over, False),
        ("Bash", {"command": "git push"}, over, False),
        ("Bash", {"command": "gh pr create"}, over, False),
        ("Bash", {"command": "pytest -q"}, over, False),
        ("Bash", {"command": "cat > handoff.md <<EOF"}, over, False),
        # A redirect sends the bytes to a file, not into the transcript. Not this guard\'s harm.
        ("Bash", {"command": "rg pattern src/ > /tmp/hits.txt"}, over, False),
    ]
    for tool, ti, r_in, want_block in block_cases:
        got = block_reason(tool, ti, r_in) is not None
        if got != want_block:
            failures.append(f"  block_reason({tool}, {ti}, {r_in}): want block={want_block}, "
                            f"got {got}")

    total = len(cases) + 1 + len(block_cases)
    if failures:
        print(f"context-guard selftest: {len(failures)}/{total} FAILED")
        print("\n".join(failures))
        return 1
    print(f"context-guard selftest: {total}/{total} passed")
    return 0


def block_reason(tool: str, tool_input: dict, r: int) -> str | None:
    """Should this tool call be refused at `r` tokens resident? None means allow.

    Pure, and tested below, because a guard that fails open looks exactly like a guard with
    nothing to say. This one can also fail CLOSED -- it can stop work -- so it is the first
    hook in this estate that has to be right in both directions.
    """
    if r < RESIDENT_BLOCK:
        return None
    if tool in _GROWING_TOOLS:
        return f"{tool} call"
    if tool == "Bash":
        cmd = str((tool_input or {}).get("command") or "")
        # A redirect means the bytes land in a FILE, not in the transcript, so it is not
        # the harm this guard exists for. `cat > handoff.md <<EOF` is how the handoff gets
        # written -- refusing it would trap the session in exactly the state it is trying
        # to escape.
        if re.search(r">>?\s*\S", cmd):
            return None
        if _BASH_READER_RE.search(cmd):
            return "read-only shell command"
    return None


BLOCK_MSG = (
    "BLOCKED by context-guard: this session is at ~{k}K resident context, above the "
    "{lim}K ceiling.\n"
    "Every turn now re-bills that whole context. Measured 2026-08-06 across 37 sessions: "
    "cache_read is 55.6% of spend, so a turn at 165K costs roughly 5x the same turn at the "
    "35K floor. Reading MORE makes every remaining turn worse.\n"
    "This refuses {what}s only. Write, Edit and every non-reading shell command still work, "
    "so you can finish and save right now:\n"
    "  1. Finish the step you are on -- you are not being cut off mid-edit.\n"
    "  2. Write the handoff (task+goal, decisions, files touched, exact next steps) to\n"
    "     {ckpt}\n"
    "  3. Commit and push what is done.\n"
    "  4. End your reply with: Safe point -- type /clear (state saved, nothing will be lost).\n"
    "The SessionStart memory-loop hook re-injects that handoff into the next session, so "
    "/clear costs nothing but the reading you would have had to redo anyway.\n"
    "If this block is WRONG -- the remaining work genuinely cannot be split -- the escape is "
    "one line, and it is the user's call, not yours:\n"
    "  touch ~/.claude/state/contextguard/OFF     # off for every session until removed\n"
)


def pretooluse(data: dict) -> int:
    """The blocking half. Exit 2 refuses the call and shows stderr to the model."""
    if os.path.exists(BLOCK_OFF):
        return 0
    path = data.get("transcript_path") or ""
    if not path:
        return 0
    r = resident(path)
    what = block_reason(data.get("tool_name") or "", data.get("tool_input") or {}, r)
    if not what:
        return 0
    ckpt = os.path.join(os.path.dirname(path), "checkpoints", "LATEST.md")
    sys.stderr.write(BLOCK_MSG.format(k=round(r / 1000), lim=RESIDENT_BLOCK // 1000,
                                      what=what, ckpt=ckpt))
    return 2


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    # One file, two hook events. They share the resident-context reader and the ceiling on
    # purpose -- a nudge and a block that disagreed about when a session is too fat would
    # teach you to ignore whichever fired first.
    if data.get("hook_event_name") == "PreToolUse":
        sys.exit(pretooluse(data))
    path = data.get("transcript_path") or ""
    if not path:
        sys.exit(0)

    state_path = path + ".guard.json"
    st = load_state(state_path)
    st["prompts"] = st.get("prompts", 0) + 1
    save_state(state_path, st)

    # ONCE per session: the plan/execute/verify standing directive. Injected on the
    # first prompt only — a per-prompt injection would be re-billed every turn, which
    # is the exact cost shape this hook exists to prevent.
    if not st.get("pev_sent") and pi_bridge_registered():
        st["pev_sent"] = True
        save_state(state_path, st)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": PEV_DIRECTIVE,
        }}))
        sys.exit(0)

    prompts = st["prompts"]
    if prompts - st.get("last_nudge_prompt", 0) < RENUDGE_EVERY and st.get("last_nudge_prompt", 0) > 0:
        sys.exit(0)  # rate-limit: already nudged recently

    r = resident(path)
    try:
        size = os.path.getsize(path)
    except Exception:
        size = 0
    age = time.time() - st.get("first_seen", time.time())

    signals, strong, fires = assess(r, prompts, size, age)
    if not fires:
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
