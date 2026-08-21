#!/usr/bin/env python3
"""waste-audit.py -- where TIME and TOKENS are LOST, attributed to a cause. READ-ONLY.

The founder, 2026-08-21: "we ned to be extre bout neasuring where tine iss lost and also
wwhre cosst is losst, tokens".

The estate already had ten cost instruments. Every one of them reports a TOTAL (by session,
by model, by day). None answers "lost to WHAT", and none measured TIME at all -- measured
2026-08-21, no script in ~/.claude/scripts/ parsed `durationMs` or `toolDenialKind`.

The window is the RECORD's own timestamp; file mtime is only the prefilter for which
files to open. Bucketing by mtime books a midnight-spanning session's whole history
into today, which is how a meter over-reports by a day.

This does one pass over the transcripts and attributes both axes to a CAUSE:

  MONEY   compaction cache-writes, denied tool calls, errored tool calls, re-read files,
          hook injections, and the marathon re-bill (turns x resident context).
  CLOCK   compaction stalls, tool execution, model generation, human think time.

Every figure comes from counters Claude Code wrote for itself. Nothing is estimated from
character counts, and nothing depends on our own code having remembered to log.

RATES are lifted verbatim from token-audit.py, which reproduces ~/.claude.json's own
`lastModelUsage` costUSD to 7+ significant figures. So this report reconciles with
estate_spend.py by construction; if the totals disagree, one of them has a bug.

WHAT IS AND IS NOT DOUBLE-COUNTED
  - Wall clock is a UNION OF INTERVALS per thread. Two tools in one parallel batch run in
    the same seconds and are counted once. The per-tool ranking is a plain SUM and is
    labelled as such, because that column answers "which tool is slow", not "how long".
  - Subagent (isSidechain) time overlaps the parent's wait by construction. It is reported
    on its own line, never added to the main thread's clock.
  - Deduped by message id, exactly as token-audit.py does: a transcript can repeat one.

Usage:
  waste-audit.py                    # today
  waste-audit.py --since 3d
  waste-audit.py --date 2026-08-20
  waste-audit.py --top 12
  waste-audit.py --json out.json
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".claude", "projects")

# $ per 1M tokens: (base_input, output). Verbatim from token-audit.py.
RATES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
READ_MULT = 0.1
WRITE_5M = 1.25
WRITE_1H = 2.0
# A gap longer than this between two records is not work, it is a session left open.
IDLE_CEILING_S = 900.0


def rate(model):
    m = (model or "").split("[")[0]
    for k, v in RATES.items():
        if m.startswith(k):
            return v
    return RATES["claude-opus-5"]


def cost(model, u):
    base, outrate = rate(model)
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", 0)
    w1 = cc.get("ephemeral_1h_input_tokens", 0)
    if not (w5 or w1):
        w1 = u.get("cache_creation_input_tokens", 0)
    return (
        u.get("input_tokens", 0) * base
        + u.get("cache_read_input_tokens", 0) * base * READ_MULT
        + w5 * base * WRITE_5M
        + w1 * base * WRITE_1H
        + u.get("output_tokens", 0) * outrate
    ) / 1e6


def resident(u):
    return (u.get("input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0))


def ts(rec):
    t = rec.get("timestamp")
    if not t:
        return None
    try:
        return dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def union_seconds(intervals):
    """Total wall clock covered by intervals, counting overlap once."""
    if not intervals:
        return 0.0
    intervals = sorted(intervals)
    total = 0.0
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s > cur_e:
            total += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
        elif e > cur_e:
            cur_e = e
    total += (cur_e - cur_s).total_seconds()
    return total


def blocks(msg):
    c = msg.get("content")
    return c if isinstance(c, list) else []


def tool_path(inp):
    """The file a tool call touched, when it names one. Read/Edit/Write name it directly;
    a shell call has to be read out of the command, which we deliberately do NOT guess at --
    an unparsed command counts as 'no path', never as a wrong path."""
    if not isinstance(inp, dict):
        return None
    for k in ("file_path", "notebook_path", "path"):
        v = inp.get(k)
        if isinstance(v, str) and v:
            return v
    return None


_HOOK_RE = __import__("re").compile(r"PreToolUse:\w+ hook error: \[[^\]]*?([\w.-]+\.(?:py|sh))[^\]]*\]")
_EXIT_RE = __import__("re").compile(r"Exit code (\d+)")


def why(text, tool):
    """Name the CAUSE of a refusal or failure, from the text the harness wrote.

    A denial and an error both cost a full context re-send, so the only useful
    question is which mechanism keeps producing them. Our own PreToolUse guards
    show up here by script name -- a guard that refuses is a guard that bills.
    """
    t = (text or "")[:600]
    m = _HOOK_RE.search(t)
    if m:
        return f"guard:{m.group(1)}"
    if "Command timed out" in t:
        return "timeout"
    if "Agent fleet cap" in t:
        return "agent fleet cap"
    if "doesn't want to proceed" in t or "user-rejected" in t:
        return "founder rejected"
    if "temporarily unavailable" in t or "overloaded" in t.lower():
        return "model unavailable"
    if "Auto mode could not evaluate" in t:
        return "auto mode could not evaluate"
    # ORDER MATTERS: a stale edit says "not found" too, and the generic branch
    # below would swallow it. Specific before general, always.
    if "String to replace not found" in t or "has not been read" in t:
        return "stale edit"
    if "requires approval" in t or "permission" in t.lower():
        return "permission"
    if "InputValidationError" in t or "validation" in t.lower():
        return "bad tool input"
    if "No such file" in t or "not found" in t:
        return "not found"
    m = _EXIT_RE.search(t)
    if m:
        return f"exit {m.group(1)}"
    first = t.strip().splitlines()[0] if t.strip() else "?"
    return first[:52]


def cmd_head(inp):
    """First meaningful word of a shell command, for ranking which commands fail."""
    if not isinstance(inp, dict):
        return None
    c = inp.get("command")
    if not isinstance(c, str):
        return None
    for tok in c.replace("(", " ").split():
        t = tok.strip("\"'`;|&$")
        if not t or "=" in t or t in ("cd", "sudo", "timeout", "env", "nohup", "!"):
            continue
        return t.split("/")[-1][:24]
    return None


class Session:
    __slots__ = ("sid", "project", "reqs", "usd", "out_usd", "ctx_usd", "turns",
                 "max_resident", "models", "first", "last")

    def __init__(self, sid, project):
        self.sid, self.project = sid, project
        self.reqs = self.turns = 0
        self.usd = self.out_usd = self.ctx_usd = 0.0
        self.max_resident = 0
        self.models = collections.Counter()
        self.first = self.last = None


def scan(paths, since_dt=None):
    A = {
        "sessions": {},
        "compactions": [],            # (durationMs, preTokens, postTokens, usd, sid)
        "denials": collections.Counter(),
        "denial_usd": 0.0,
        "denial_out_tok": 0,
        "errors": collections.Counter(),
        "why_denied": collections.Counter(),
        "why_denied_usd": collections.Counter(),
        "why_error": collections.Counter(),
        "why_error_usd": collections.Counter(),
        "bad_cmd": collections.Counter(),
        "error_usd": 0.0,
        "tool_sum_s": collections.Counter(),
        "tool_calls": collections.Counter(),
        "tool_slowest": {},
        "clock": collections.Counter(),   # main-thread union seconds by phase
        "sidechain_s": 0.0,
        "unfinished_tools": 0,
        "rereads": collections.Counter(),  # (sid, path) -> count
        "reread_paths": collections.Counter(),
        "hook_bytes": 0,
        "hook_fires": collections.Counter(),
        "total_usd": 0.0,
        "total_out_usd": 0.0,
        "total_ctx_usd": 0.0,
        "requests": 0,
        "files": 0,
        "parse_errors": 0,
    }

    for path in paths:
        project = os.path.basename(os.path.dirname(path))
        A["files"] += 1
        seen_msg = set()
        # per-file timelines
        main_intervals = {"tool": [], "gen": [], "human": [], "compact": []}
        side_intervals = []
        pending = {}      # tool_use_id -> (start_ts, name, is_side)
        last_asst_end = None
        last_rec_ts = None
        last_req_cost = 0.0
        read_counts = collections.Counter()

        try:
            fh = open(path, errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    A["parse_errors"] += 1
                    continue
                rtype = d.get("type")
                t = ts(d)
                if since_dt is not None and t is not None and t < since_dt:
                    continue          # file mtime is only the prefilter; the record's
                                      # own timestamp is the window. A session spanning
                                      # midnight would otherwise book yesterday's spend.
                sid = d.get("sessionId") or d.get("session_id") or os.path.basename(path)[:8]
                side = bool(d.get("isSidechain"))

                if rtype == "assistant":
                    msg = d.get("message") or {}
                    u = msg.get("usage")
                    mid = msg.get("id")
                    if u and msg.get("model") != "<synthetic>" and mid not in seen_msg:
                        seen_msg.add(mid)
                        model = msg.get("model")
                        c = cost(model, u)
                        base, outrate = rate(model)
                        oc = u.get("output_tokens", 0) * outrate / 1e6
                        s = A["sessions"].get(sid)
                        if s is None:
                            s = A["sessions"][sid] = Session(sid, project)
                        s.reqs += 1
                        s.usd += c
                        s.out_usd += oc
                        s.ctx_usd += c - oc
                        s.models[(model or "?").split("[")[0]] += 1
                        s.max_resident = max(s.max_resident, resident(u))
                        if t:
                            s.first = t if s.first is None else min(s.first, t)
                            s.last = t if s.last is None else max(s.last, t)
                        A["total_usd"] += c
                        A["total_out_usd"] += oc
                        A["total_ctx_usd"] += c - oc
                        A["requests"] += 1
                        last_req_cost = c
                        # generation wall clock: previous record -> this assistant record
                        if t and last_rec_ts and 0 < (t - last_rec_ts).total_seconds() <= IDLE_CEILING_S:
                            (side_intervals if side else main_intervals["gen"]).append((last_rec_ts, t))
                    for b in blocks(msg):
                        if b.get("type") == "tool_use" and t:
                            pending[b.get("id")] = (t, b.get("name"), side,
                                                    tool_path(b.get("input")),
                                                    cmd_head(b.get("input")))
                    last_asst_end = t

                elif rtype == "user":
                    msg = d.get("message") or {}
                    if d.get("toolDenialKind"):
                        A["denials"][d.get("toolDenialKind")] += 1
                        A["denial_usd"] += last_req_cost
                        w = why(d.get("toolUseResult"), None)
                        A["why_denied"][w] += 1
                        A["why_denied_usd"][w] += last_req_cost
                    for b in blocks(msg):
                        if b.get("type") != "tool_result":
                            continue
                        tid = b.get("tool_use_id")
                        got = pending.pop(tid, None)
                        if b.get("is_error"):
                            A["errors"][(got[1] if got else "?")] += 1
                            A["error_usd"] += last_req_cost
                            w = why(b.get("content") if isinstance(b.get("content"), str)
                                    else d.get("toolUseResult"), got[1] if got else None)
                            A["why_error"][w] += 1
                            A["why_error_usd"][w] += last_req_cost
                            if got and got[4]:
                                A["bad_cmd"][got[4]] += 1
                        if got and t:
                            start, name, is_side, fpath, chead = got
                            secs = (t - start).total_seconds()
                            if 0 <= secs <= IDLE_CEILING_S:
                                A["tool_sum_s"][name] += secs
                                A["tool_calls"][name] += 1
                                if secs > A["tool_slowest"].get(name, (0, ""))[0]:
                                    A["tool_slowest"][name] = (secs, os.path.basename(path))
                                (side_intervals if is_side else main_intervals["tool"]).append((start, t))
                            if fpath:
                                read_counts[(sid, fpath)] += 1
                    # human think time: typed prompt after an assistant turn
                    origin = d.get("origin") or {}
                    typed = d.get("promptSource") == "typed" or origin.get("kind") == "human"
                    if typed and t and last_asst_end:
                        gap = (t - last_asst_end).total_seconds()
                        if 0 < gap <= IDLE_CEILING_S:
                            main_intervals["human"].append((last_asst_end, t))
                        s = A["sessions"].get(sid)
                        if s:
                            s.turns += 1

                elif rtype == "system" and d.get("subtype") == "compact_boundary":
                    cm = d.get("compactMetadata") or {}
                    dur = cm.get("durationMs", 0) or 0
                    pre = cm.get("preTokens", 0) or 0
                    post = cm.get("postTokens", 0) or 0
                    # the compaction re-writes the surviving context as a fresh cache write
                    # on the main loop (1h TTL, 2x) and re-reads nothing -- priced on the
                    # session's dominant model.
                    s = A["sessions"].get(sid)
                    model = s.models.most_common(1)[0][0] if (s and s.models) else "claude-opus-5"
                    base, _ = rate(model)
                    usd = post * base * WRITE_1H / 1e6
                    A["compactions"].append((dur, pre, post, usd, sid))
                    if t and dur:
                        start = t - dt.timedelta(milliseconds=dur)
                        main_intervals["compact"].append((start, t))

                elif rtype == "attachment":
                    att = d.get("attachment") or {}
                    if isinstance(att, dict) and att.get("type") == "hook_success":
                        A["hook_fires"][att.get("hookName", "?")] += 1
                        A["hook_bytes"] += len(str(att.get("content") or ""))

                if t:
                    last_rec_ts = t

        A["unfinished_tools"] += len(pending)
        for phase, iv in main_intervals.items():
            A["clock"][phase] += union_seconds(iv)
        A["sidechain_s"] += union_seconds(side_intervals)
        for (sid, fpath), n in read_counts.items():
            if n > 1:
                A["rereads"][(sid, fpath)] = n
                A["reread_paths"][fpath] += n - 1
    return A


def hms(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def collect(since_ts, date_filter):
    out = []
    if not os.path.isdir(ROOT):
        return out
    for d in os.scandir(ROOT):
        if not d.is_dir():
            continue
        try:
            entries = list(os.scandir(d.path))
        except OSError:
            continue
        for f in entries:
            if not f.name.endswith(".jsonl"):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if since_ts and st.st_mtime < since_ts:
                continue
            if date_filter:
                day = dt.date.fromtimestamp(st.st_mtime).isoformat()
                if day < date_filter:
                    continue
            out.append(f.path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="1d", help="1d / 3d / 12h; window of transcript activity")
    ap.add_argument("--date", help="YYYY-MM-DD; files touched on or after this day")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", help="also dump machine-readable")
    args = ap.parse_args()

    since_ts = None
    if args.date:
        since_ts = dt.datetime.fromisoformat(args.date).timestamp()
    elif args.since:
        n = float(args.since[:-1])
        unit = args.since[-1]
        mult = {"d": 86400, "h": 3600, "m": 60}.get(unit)
        if mult is None:
            sys.exit("--since must end in d/h/m")
        since_ts = dt.datetime.now().timestamp() - n * mult

    paths = collect(since_ts, args.date)
    if not paths:
        sys.exit("no transcripts in window")
    since_dt = (dt.datetime.fromtimestamp(since_ts, dt.timezone.utc)
                if since_ts else None)
    A = scan(paths, since_dt)

    W = 78
    label = args.date or f"last {args.since}"
    print("=" * W)
    print(f"WASTE AUDIT  {label}   {len(paths)} transcripts, {A['requests']:,} requests")
    print("=" * W)
    print(f"  billed          ${A['total_usd']:,.2f}")
    ctx_pct = 100 * A["total_ctx_usd"] / A["total_usd"] if A["total_usd"] else 0
    print(f"  context transport ${A['total_ctx_usd']:,.2f}  {ctx_pct:.0f}%"
          f"   |  output ${A['total_out_usd']:,.2f}  {100-ctx_pct:.0f}%")

    # ---------------- WHERE COST IS LOST ----------------
    print()
    print("-" * W)
    print("WHERE COST IS LOST -- billed tokens that bought no work product")
    print("-" * W)
    comp_usd = sum(c[3] for c in A["compactions"])
    comp_n = len(A["compactions"])
    comp_pre = sum(c[1] for c in A["compactions"])
    lost = []
    if comp_n:
        lost.append(("compaction cache re-writes",
                     comp_usd,
                     f"{comp_n} compactions, {comp_pre:,} tok dropped, re-written at 2x"))
    if A["denials"]:
        lost.append(("denied tool calls", A["denial_usd"],
                     f"{sum(A['denials'].values())} denials: "
                     + ", ".join(f"{k}={v}" for k, v in A["denials"].most_common(4))))
    if A["errors"]:
        lost.append(("errored tool calls", A["error_usd"],
                     f"{sum(A['errors'].values())} errors: "
                     + ", ".join(f"{k}={v}" for k, v in A["errors"].most_common(4))))
    rr = sum(A["reread_paths"].values())
    if rr:
        lost.append(("re-read files (same path, same session)", 0.0,
                     f"{rr} redundant reads over {len(A['reread_paths'])} paths"))
    for name, usd, note in sorted(lost, key=lambda x: -x[1]):
        amt = f"${usd:>9,.2f}" if usd else "    (unpriced)"
        print(f"  {amt}  {name}")
        print(f"              {note}")
    if not lost:
        print("  nothing attributable in window")

    if A["why_denied"] or A["why_error"]:
        print()
        print("  WHAT IS DOING THE REFUSING / FAILING (each one re-sends the whole context):")
        merged = collections.Counter()
        for k, v in A["why_denied_usd"].items():
            merged[k] += v
        for k, v in A["why_error_usd"].items():
            merged[k] += v
        cnt = A["why_denied"] + A["why_error"]
        for k, usd in merged.most_common(args.top):
            print(f"    ${usd:>8,.2f}  {cnt[k]:>5}x  {k}")
    if A["bad_cmd"]:
        print()
        print("  shell commands that failed most:")
        for c, n in A["bad_cmd"].most_common(8):
            print(f"    {n:>5}x  {c}")

    if A["reread_paths"]:
        print()
        print("  most re-read paths (each repeat re-bills its content on every later turn):")
        for p, n in A["reread_paths"].most_common(args.top):
            print(f"    {n:>4} repeats  {p}")

    # ---------------- MARATHON RE-BILL ----------------
    print()
    print("-" * W)
    print("THE MARATHON RE-BILL -- cost = turns x resident context, ranked by session")
    print("-" * W)
    print(f"  {'$ billed':>10} {'ctx%':>5} {'reqs':>6} {'maxctx':>8}  session / project")
    ses = sorted(A["sessions"].values(), key=lambda s: -s.usd)
    for s in ses[:args.top]:
        pct = 100 * s.ctx_usd / s.usd if s.usd else 0
        print(f"  {s.usd:>10,.2f} {pct:>4.0f}% {s.reqs:>6} {s.max_resident/1000:>7.0f}K  "
              f"{s.sid[:8]}  {s.project[-42:]}")
    if len(ses) > args.top:
        rest = sum(s.usd for s in ses[args.top:])
        print(f"  {rest:>10,.2f}    --  {len(ses)-args.top} more sessions")

    # ---------------- WHERE TIME IS LOST ----------------
    print()
    print("-" * W)
    print("WHERE TIME IS LOST -- main-thread wall clock, overlap counted once")
    print("-" * W)
    clock = A["clock"]
    total_clock = sum(clock.values())
    order = ["tool", "gen", "compact", "human"]
    names = {"tool": "tool execution (the agent waiting on a command)",
             "gen": "model generating",
             "compact": "compaction stalls",
             "human": "human think time (not ours to save)"}
    for k in order:
        v = clock.get(k, 0)
        pct = 100 * v / total_clock if total_clock else 0
        print(f"  {hms(v):>8}  {pct:>4.0f}%  {names[k]}")
    print(f"  {hms(A['sidechain_s']):>8}    --  subagent time (overlaps the above, not added)")
    if comp_n:
        durs = sorted(c[0] for c in A["compactions"])
        med = durs[len(durs)//2] / 1000
        print(f"            compaction: {comp_n} x median {med:.0f}s"
              f" = {hms(sum(durs)/1000)} of pure stall")

    print()
    print("  slowest tools (SUM of call durations; parallel batches overlap, so this")
    print("  ranks which tool is slow, it is not additive wall clock):")
    print(f"    {'total':>8} {'calls':>6} {'mean':>7} {'worst':>7}  tool")
    for name, secs in A["tool_sum_s"].most_common(args.top):
        n = A["tool_calls"][name]
        worst = A["tool_slowest"].get(name, (0, ""))[0]
        print(f"    {hms(secs):>8} {n:>6} {secs/n:>6.1f}s {worst:>6.0f}s  {name}")
    if A["unfinished_tools"]:
        print(f"    ({A['unfinished_tools']} tool calls have no result in the transcript --"
              f" killed, backgrounded or session ended)")

    if A["hook_fires"]:
        print()
        print(f"  hook injections: {sum(A['hook_fires'].values())} fires,"
              f" {A['hook_bytes']:,} chars (~{A['hook_bytes']//4:,} tok) into context")
        for h, n in A["hook_fires"].most_common(5):
            print(f"    {n:>5}  {h}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump({
                "window": label,
                "requests": A["requests"],
                "total_usd": A["total_usd"],
                "ctx_usd": A["total_ctx_usd"],
                "out_usd": A["total_out_usd"],
                "compactions": comp_n,
                "compaction_usd": comp_usd,
                "compaction_stall_s": sum(c[0] for c in A["compactions"]) / 1000,
                "clock": dict(A["clock"]),
                "sidechain_s": A["sidechain_s"],
                "tool_sum_s": dict(A["tool_sum_s"]),
                "tool_calls": dict(A["tool_calls"]),
                "denials": dict(A["denials"]),
                "why_denied_usd": dict(A["why_denied_usd"]),
                "why_error_usd": dict(A["why_error_usd"]),
                "bad_cmd": dict(A["bad_cmd"]),
                "errors": dict(A["errors"]),
                "rereads": {p: n for p, n in A["reread_paths"].most_common(200)},
                "sessions": [{"sid": s.sid, "project": s.project, "usd": s.usd,
                              "ctx_usd": s.ctx_usd, "reqs": s.reqs,
                              "max_resident": s.max_resident} for s in ses[:200]],
            }, fh, indent=1)
        print(f"\n  json -> {args.json}")


if __name__ == "__main__":
    main()
