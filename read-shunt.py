#!/usr/bin/env python3
"""read-shunt.py -- route a bulk file read to a cheap worker model; the frontier model gets a digest.

Founder, 2026-09-09 (record ~/.claude/docs/founder/2026-09-09T0357Z-i-dnt-get-ur-reposne-for-this-es-de40bd62.md):
Claude Code stays only if its cost is slashed. The pattern is Spotify's Shunt plugin: a PreToolUse
hook intercepts reads over a line threshold and hands the file to a cheap worker, which returns a
structured digest. Spotify measured about 90% fewer tokens on bulk reads. Their plugin needs
Portal; this is the same three layers on the estate's own LiteLLM proxy (R34 provider agnostic:
the worker is whatever alias READ_SHUNT_MODEL names). Founder 2026-09-09: "Any file read over 350 lines use minimax"; measured the same day on the digest prompt, MiniMax-M3 spent 1499 of 1500 and 2999 of 3000 tokens on reasoning and returned 2 chars even with reasoning_effort none, so the default worker is `minimax_m27` (MiniMax-M2.7, same fixed-fee account: 2406 chars in 31 s; founder 2026-09-09: "we pay fixed fee for minimax, we need to get usage out of it"), then `gemini` (free tier, 3249 chars in 0.5 s, but a free quota runs out), then `minimax` (M3). DeepSeek is the lead engineer, never a reader (founder, same day).

What it grades: PreToolUse on Read (any path, no offset/limit) and on Bash when the command is a
bare `cat <one file>`. A read with offset/limit is an exact-range read and passes untouched; that is
the escape hatch the digest names. Files under READ_SHUNT_LINES (350) pass. Anything the worker
cannot answer in READ_SHUNT_TIMEOUT seconds passes: a guard that refuses correct work is an outage
(LAW 38), so every failure is fail-open and recorded.

Ledger (LAW 28): one line per shunted read in $READ_SHUNT_LEDGER or ~/.claude/state/read-shunt.jsonl
    {at, file, lines, file_chars, digest_chars, worker_prompt_tokens, worker_completion_tokens,
     est_frontier_tokens_avoided, ms, outcome}
est_frontier_tokens_avoided is (file_chars - digest_chars) / 4: the rough token count Claude did
not ingest. `read-shunt.py --report` sums the ledger; that is the number, never a memory.
Off switch: READ_SHUNT=off.
"""

from __future__ import annotations
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

HOME = os.path.expanduser("~")
THRESHOLD = int(os.environ.get("READ_SHUNT_LINES", "350"))
MAX_CHARS = int(os.environ.get("READ_SHUNT_MAX_CHARS", "400000"))
TIMEOUT = float(os.environ.get("READ_SHUNT_TIMEOUT", "60"))
MODEL = os.environ.get("READ_SHUNT_MODEL", "minimax_m27")
# MiniMax-M3 is a reasoning model: measured 2026-09-09 09:58Z, a 900-token budget was spent whole on
# reasoning_content (899 tokens), content came back 2 chars and finish_reason was `length`. The request
# now asks for reasoning_effort none; 1500 covers a 2500-char digest with room. Founder 2026-09-09:
# DeepSeek is the lead engineer, not a reader, so it is not in this chain; the fallbacks are the
# free-tier lanes the router key may use.
MAX_TOKENS = int(os.environ.get("READ_SHUNT_MAX_TOKENS", "1500"))
# A worker that answers 429, 5xx or an unknown-model 4xx hands the read to the next alias, never back to the frontier
# model: measured 2026-09-09 04:40Z, minimax answered 429 in 267 ms and a 1261-line file went to
# Claude whole. The chain ends at the frontier only when every alias has refused.
FALLBACKS = [
    m
    for m in os.environ.get("READ_SHUNT_FALLBACK", "gemini,minimax").split(",")
    if m.strip() and m.strip() != MODEL
]
LEDGER = os.environ.get("READ_SHUNT_LEDGER") or os.path.join(
    HOME, ".claude", "state", "read-shunt.jsonl"
)


class EmptyDigest(RuntimeError):
    """The worker answered 200 with no content; graded like a 5xx, never shown to the frontier."""


CAT_RE = re.compile(r"^\s*cat\s+(?:-[A-Za-z]+\s+)?(['\"]?)([^\s'\"|;&<>]+)\1\s*$")

PROMPT = """You are a code-reading worker for a senior engineer who will NOT see this file. Produce a digest they can act on without reading it. Be exact and dense; no preamble. HARD BUDGET: the whole digest must be under 2500 characters. Prefer line ranges over prose.

FILE: {path} ({lines} lines)

Return, in this order, as plain text with these headings:
PURPOSE: one or two sentences.
STRUCTURE: the top-level units (functions, classes, sections, resources) as `L<start>-L<end> <name>: <=8 words`. Fold imports, constants and trivia into one line each. Cover the whole file span.
KEY VALUES: constants, env vars, paths, ports, hosts, versions, flags, external calls (line numbers).
NOTABLE: bugs, TODOs, dead code, security or correctness smells, things that contradict their own comments (line numbers). Say "none found" if none.
READ EXACTLY: the 1-3 line ranges most worth reading verbatim for the likeliest tasks (edit, debug, extend), and why.

FILE CONTENT:
{body}
"""


def _key() -> str:
    k = os.environ.get("LITELLM_API_KEY", "")
    if not k:
        p = os.path.join(HOME, ".config", "prospector", "secrets.d", "LITELLM_API_KEY")
        try:
            k = open(p).read().strip()
        except OSError:
            k = ""
    return k


def _base() -> str:
    # LAW 46: the zone is never a literal here. LITELLM_BASE_URL (the session env exports it) or
    # llm.<ESTATE_ZONE>; with neither, the shunt has no worker and passes the read through.
    base = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
    if not base and os.environ.get("ESTATE_ZONE"):
        base = f"https://llm.{os.environ['ESTATE_ZONE']}/v1"
    if not base.startswith("https://"):
        raise ValueError(f"no https LiteLLM base: LITELLM_BASE_URL={base!r}")
    return base


def _ledger(row: dict) -> None:
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception as e:  # the ledger may never fail the hook (LAW 38)
        print(f"read-shunt: ledger not written: {e}", file=sys.stderr)


def _target(payload: dict) -> str | None:
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    if tool == "Read":
        if ti.get("offset") or ti.get("limit") or ti.get("pages"):
            return None
        return ti.get("file_path")
    if tool == "Bash":
        m = CAT_RE.match(ti.get("command", "") or "")
        if not m:
            return None
        path = os.path.expanduser(os.path.expandvars(m.group(2)))
        if not os.path.isabs(path):
            path = os.path.join(payload.get("cwd") or os.getcwd(), path)
        return path
    return None


def _worker(path: str, lines: int, body: str) -> tuple[str, dict, str]:
    import urllib.error

    last: Exception | None = None
    for model in [MODEL, *FALLBACKS]:
        try:
            digest, usage = _ask(model, path, lines, body)
            return digest, usage, model
        except (urllib.error.HTTPError, EmptyDigest) as e:
            last = e
            if getattr(e, "code", None) == 401:
                raise  # the key is wrong for every alias; no point asking the next one
            # 403 falls through: LiteLLM answers 403 when this key may not use that one alias.
            print(
                f"read-shunt: {model} answered {getattr(e, 'code', 'empty')}; trying the next worker",
                file=sys.stderr,
            )
    raise last if last else RuntimeError("no worker model configured")


def _ask(model: str, path: str, lines: int, body: str) -> tuple[str, dict]:
    req = urllib.request.Request(  # noqa: S310 scheme pinned to https in _base()
        _base() + "/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": PROMPT.format(path=path, lines=lines, body=body),
                    }
                ],
                "max_tokens": MAX_TOKENS,
                "temperature": 0,
                # measured 2026-09-09 10:05Z on the 1261-line bin/catalog-gen: without this MiniMax-M3
                # spent every token on reasoning_content and returned 2 chars; with it, 1313 chars of
                # answer in 9.9 s (179 reasoning tokens); gemini 751 chars in 2.5 s, zero reasoning.
                "reasoning_effort": "none",
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {_key()}",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 scheme pinned to https in _base()
        d = json.load(r)
    digest = (d["choices"][0]["message"].get("content") or "").strip()
    if not digest:
        # measured 2026-09-09 08:54Z: minimax answered 200 with empty content for a 1261-line file
        # and the frontier model got a refusal with nothing behind it. An empty digest is a
        # refused read with no reading; hand it to the next worker like a 5xx.
        raise EmptyDigest(f"{model} answered 200 with an empty digest")
    return digest, d.get("usage") or {}


def report() -> int:
    n = tok = saved = 0
    try:
        for line in open(LEDGER):
            r = json.loads(line)
            if r.get("outcome") != "shunted":
                continue
            n += 1
            tok += int(r.get("worker_prompt_tokens", 0)) + int(
                r.get("worker_completion_tokens", 0)
            )
            saved += int(r.get("est_frontier_tokens_avoided", 0))
    except OSError as e:  # no ledger yet is a zero report, not a failure
        print(f"read-shunt: no ledger read: {e}", file=sys.stderr)
    print(
        json.dumps(
            {
                "shunted_reads": n,
                "worker_tokens": tok,
                "est_frontier_tokens_avoided": saved,
                "ledger": LEDGER,
            }
        )
    )
    return 0


def main() -> int:
    if "--report" in sys.argv:
        return report()
    if os.environ.get("READ_SHUNT", "on").lower() in ("off", "0", "false"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    path = _target(payload)
    if not path or not os.path.isfile(path):
        return 0
    t0 = time.time()
    row = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "file": path,
        "session": payload.get("session_id", ""),
        "model": MODEL,
    }
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_CHARS + 1)
        if b"\0" in raw[:8000]:
            return 0
        body = raw[:MAX_CHARS].decode("utf-8", "replace")
        truncated = len(raw) > MAX_CHARS
        lines = body.count("\n") + (0 if body.endswith("\n") else 1)
        if lines <= THRESHOLD and not truncated:
            return 0
        if truncated:
            body += f"\n[... truncated at {MAX_CHARS} chars; the rest was not sent ...]"
        digest, usage, model = _worker(path, lines, body)
        row["model"] = model
    except Exception as e:  # fail open, record why
        row.update(
            outcome="passed-through",
            error=f"{type(e).__name__}: {e}"[:200],
            ms=int((time.time() - t0) * 1000),
        )
        _ledger(row)
        return 0
    file_chars, digest_chars = len(body), len(digest)
    row.update(
        outcome="shunted",
        lines=lines,
        file_chars=file_chars,
        digest_chars=digest_chars,
        worker_prompt_tokens=usage.get("prompt_tokens", 0),
        worker_completion_tokens=usage.get("completion_tokens", 0),
        est_frontier_tokens_avoided=max(0, (file_chars - digest_chars) // 4),
        ms=int((time.time() - t0) * 1000),
    )
    _ledger(row)
    reason = (
        f"read-shunt: {path} is {lines} lines (over {THRESHOLD}); the full read went to the worker model "
        f"`{model}` and this digest came back instead. For exact text call Read with offset and limit "
        f"(a ranged read is never shunted); the READ EXACTLY section names the ranges worth it.\n\n{digest}"
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    # hook-run grades a crashed hook as a refusal (crew#603), so a crash here would refuse every
    # read and every shell call in the estate. The shunt is an optimisation, never a gate: it
    # exits 0 on anything it did not foresee.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"read-shunt: passed through: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(0)
