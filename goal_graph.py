#!/usr/bin/env python3
"""The goal net: objectives as a graph, a walk back to core, and a return path after a switch.

Founder asks, 2026-08-24, verbatim: "we need to detect also when agebt is drifint fro core
objectives and nudge then back", "we need strig contet switchuig oritovol checkpoit
nagaenent, autnated if possible", "should be graph like", "or netowr/graph like sorry laynan
speak", "you can work your way back to core goakls, reerach online", "but you hould be able
to trck whe contet switches but go back and conplete wht you were doing befor cotet
switched", "and it need to traverse all goal and ensure net", "needs exhaustve dge cse
testing".

WHAT WAS ALREADY HERE, AND WHY THIS IS NOT A SECOND GUARD
---------------------------------------------------------
`goal-guard.py` has held the objective since 2026-08-21. It counts read-only calls since the
last write and, past a per-lane limit, injects a walk-back. It works, and it is kept.

What it holds is one string. `state/goal/<session>.json` has a single `goal` field, so there
is nothing to walk back ALONG -- the guard can only reprint the sentence. Measured on this
machine, 2026-08-24 03:02, session 8ef72725: `"goal": ""`, `"fired": 34`, `"calls": 1183`.
Thirty-four walk-backs fired into a session that had no goal on disk, so every one of them
printed "(none on disk)". That is the gap this module fills, and it fills it by giving
goal-guard a structure to read rather than by firing a second time.

THE MODEL, AND WHY A GRAPH RATHER THAN A LIST
----------------------------------------------
Nodes are objectives and tasks. Edges point at PARENTS, so an edge means "this exists in
order to serve that". A node with no parents is a root; a root whose kind is `core` is a core
objective. Parents are a list rather than one field because real work serves two objectives
at once -- a fix that both unblocks a customer and closes a recurring class -- and a tree
forces you to lie about which. That is the difference between a tree and a net, and the net
is what the founder asked for.

Direction matters and it is the whole reason the walk-back is cheap. Every node knows its
parents, so walking from wherever the agent is standing up to the core objectives is a graph
traversal with no search: `--path` prints it. Walking DOWN, from core objectives to
everything open beneath them, is the other direction and is what `--net` does.

WHY GOING DEEPER IS NOT A CONTEXT SWITCH
-----------------------------------------
The load-bearing distinction. If the agent moves to a node BELOW where it is standing, it has
decomposed the work, which is the job. If it moves to a node ABOVE, it has finished a piece
and come back up. Only a move SIDEWAYS -- to a node that is neither an ancestor nor a
descendant -- is a context switch, and only that pushes the abandoned node onto a stack with
a checkpoint so it can be returned to.

Without that rule every decomposition would read as drift, the stack would fill with nodes
the agent is still working on, and the nudge would fire constantly until an agent learned to
ignore it. LAW 38: a guard that refuses correct work is an outage, and a guard that nags
about correct work is the same outage with a slower fuse.

WHY IT NUDGES AND NEVER REFUSES
--------------------------------
Same reason goal-guard advises. A switch is often right -- LAW 1 says a fire outranks the
named job, and LAW 8 says a trap you trip over is fixed where you found it. The failure is
not switching, it is switching and never coming back. So the stack is the deliverable, not
the fence: park the node, keep the checkpoint, and say what is waiting every time the agent
looks.

WHAT THE FIELD DOES, read 2026-08-24
-------------------------------------
- Trajectory-level intent drift is measured as a distance between the user's intent and the
  agent's actions, scored per step, because individual steps each look correct while the
  trajectory diverges (Intent Drift Score, NeurIPS 2025; DeepContext, arXiv 2602.16935).
  Here the distance is structural instead of semantic: reachability from a core node. An
  estate of six sessions cannot afford a model call per tool call, and reachability is exact
  where an embedding distance is a threshold somebody has to tune.
- The 2026 agent-drift work splits drift into semantic (departure from intent), coordination
  (consensus breakdown) and behavioural (unintended strategies). This module detects the
  first structurally and the second not at all -- LAW 26's board is the coordination layer.
- HTN planners already do the thing the founder described: on a failure they do not restart
  from the root goal, they find the minimal subtree to revise and resume, leaving the rest of
  the plan intact. That is `--resume` popping one stack frame rather than replanning.
- LangGraph and Temporal solve the durable half with checkpointers and thread ids, and the
  published criticism of checkpointers is exactly our case: a run lives in one process, so
  when the process dies the run dies with it. A session here IS that process. The stack lives
  on disk, keyed by session, so a compaction or a crash does not take the return path with
  it.

WHAT THIS DOES NOT DO
----------------------
It does not read the transcript, score meaning, or call a model. Drift here is six mechanical
signals over the graph, listed in `drift()`. Each is a fact about the structure that a command
can check, which is the only kind of signal this estate accepts (LAW 2, LAW 33).

    python3 goal_graph.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

HOME = Path.home()
STATE_DIR = HOME / ".claude" / "state" / "goals"
LEDGER = HOME / ".claude" / "state" / "goal-net.jsonl"

VERSION = 1

KINDS = ("core", "goal", "task")
STATUSES = ("open", "active", "parked", "done", "dropped")
CLOSED = ("done", "dropped")

# Starting values, not measured thresholds. Every firing is written to LEDGER with its
# signal name, so the real numbers are measurable from the ledger within a week and these
# replaced by ones that were counted. Same discipline as goal-guard's readonly_run_limit,
# which started at 25 as a guess and was measured to 16.
PARK_MAX_SECONDS = 1800     # a parked node older than this is abandoned, not parked
PARK_MAX_TICKS = 60         # or this many tool calls, whichever comes first
STALL_TICKS = 80            # active node unchanged, nothing opened or closed beneath it
THRASH_SWITCHES = 3         # switches ...
THRASH_WINDOW_TICKS = 20    # ... inside this many tool calls
STACK_SOFT_DEPTH = 4        # deeper than this and the nudge escalates
NUDGE_EVERY_TICKS = 20      # a standing signal repeats this often, a new one fires at once
MAX_TEXT = 500
MAX_NODES = 2000            # a graph past this is a bug, not a plan

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------

class GraphError(ValueError):
    """A refusal that names what was wrong. Never raised at a hook; see safe_*."""


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------

def _now() -> int:
    return int(time.time())


def session_key(session: str) -> str:
    """A filename that cannot escape STATE_DIR whatever the session id contains."""
    # No dots survive, so no arrangement of the input can produce `..` or a suffix that
    # changes what the file is. A session id arrives from an environment variable, which
    # is the kind of input that is trusted right up until it is not.
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session or "unknown")[:120]
    return safe or "unknown"


def state_path(session: str, root: Optional[Path] = None) -> Path:
    return (root or STATE_DIR) / f"{session_key(session)}.json"


def empty_graph(session: str = "") -> dict:
    return {
        "version": VERSION,
        "session": session,
        "nodes": {},
        "active": None,
        "stack": [],
        "switches": [],
        "tick": 0,
        "seq": 0,
    }


def load(session: str, root: Optional[Path] = None) -> dict:
    """Read a graph. A missing or unreadable file is an empty graph, never an exception.

    Unreadable includes truncated JSON, which is what a crash mid-write leaves behind. A
    hook that raised there would take the session down with it, so the file is rebuilt
    instead and the loss is one session's plan rather than the session.
    """
    p = state_path(session, root)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError, UnicodeDecodeError):
        return empty_graph(session)
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), dict):
        return empty_graph(session)
    g = empty_graph(session)
    g.update(raw)
    g["session"] = session or raw.get("session", "")
    # Repair the shapes a hand edit can break, rather than trusting them downstream.
    if not isinstance(g.get("stack"), list):
        g["stack"] = []
    if not isinstance(g.get("switches"), list):
        g["switches"] = []
    for key in ("tick", "seq"):
        if not isinstance(g.get(key), int) or g[key] < 0:
            g[key] = 0
    if g.get("active") is not None and not isinstance(g["active"], str):
        g["active"] = None
    return g


def save(g: dict, root: Optional[Path] = None) -> None:
    """Write atomically. A half-written graph reads as no graph, which loses the plan."""
    p = state_path(g.get("session", ""), root)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".goalnet-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(g, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ledger(entry: dict, path: Optional[Path] = None) -> None:
    """Append one line. LAW 28: a signal nobody can count later is not a signal."""
    p = path or LEDGER
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        entry = dict(entry)
        entry.setdefault("at", _now())
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# traversal
# --------------------------------------------------------------------------

def parents_of(g: dict, nid: str) -> list:
    n = g["nodes"].get(nid) or {}
    ps = n.get("parents")
    return [p for p in ps if isinstance(p, str)] if isinstance(ps, list) else []


def children_of(g: dict, nid: str) -> list:
    return sorted(k for k, n in g["nodes"].items() if nid in (n.get("parents") or []))


def ancestors(g: dict, nid: str) -> set:
    """Every node reachable by walking parents. Cycle-safe: a visited set, not recursion.

    A cycle cannot be created through the API -- ``add`` and ``reparent`` refuse one -- but
    a hand-edited file can hold one, and the traversal that reports it must not hang while
    doing so.
    """
    seen: set = set()
    stack = list(parents_of(g, nid))
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in g["nodes"]:
            continue
        seen.add(cur)
        stack.extend(parents_of(g, cur))
    return seen


def descendants(g: dict, nid: str) -> set:
    seen: set = set()
    stack = children_of(g, nid)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children_of(g, cur))
    return seen


def roots(g: dict) -> list:
    return sorted(k for k in g["nodes"] if not parents_of(g, k))


def cores(g: dict) -> list:
    return sorted(k for k, n in g["nodes"].items() if n.get("kind") == "core")


def path_to_core(g: dict, nid: str) -> list:
    """The shortest walk from *nid* up to a core objective, as a list of ids.

    Shortest rather than every path: the point is to show an agent the way back in one
    line. `--net` is where every path is checked. Returns [] when nid is unknown, and
    [nid] alone when nid is itself core.
    """
    if nid not in g["nodes"]:
        return []
    if g["nodes"][nid].get("kind") == "core":
        return [nid]
    seen = {nid}
    frontier = [(nid, [nid])]
    while frontier:
        nxt = []
        for cur, trail in frontier:
            for p in parents_of(g, cur):
                if p in seen or p not in g["nodes"]:
                    continue
                trail2 = trail + [p]
                if g["nodes"][p].get("kind") == "core":
                    return trail2
                seen.add(p)
                nxt.append((p, trail2))
        frontier = nxt
    return []


def reaches_core(g: dict, nid: str) -> bool:
    return bool(path_to_core(g, nid))


def relation(g: dict, frm: Optional[str], to: str) -> str:
    """How *to* stands to *frm*: same, deeper, shallower, or sideways.

    This is the rule that decides whether a move is a context switch. Sideways is the only
    one that is.
    """
    if frm is None or frm not in g["nodes"]:
        return "first"
    if frm == to:
        return "same"
    if frm in ancestors(g, to):
        return "deeper"
    if to in ancestors(g, frm):
        return "shallower"
    return "sideways"


# --------------------------------------------------------------------------
# mutations
# --------------------------------------------------------------------------

def _mkid(g: dict, text: str) -> str:
    g["seq"] = int(g.get("seq", 0)) + 1
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:24].strip("-")
    return f"n{g['seq']}" + (f"-{slug}" if slug else "")


def add(
    g: dict,
    text: str,
    parents: Iterable[str] = (),
    kind: str = "task",
    nid: Optional[str] = None,
    now: Optional[int] = None,
) -> str:
    """Create a node. Returns its id.

    Refuses, rather than silently accepting: an unknown parent, a self-parent, an edge that
    would close a cycle, a duplicate id, an id that is not a safe token, empty text, and a
    graph already at MAX_NODES. Each of those is a plan that cannot be traversed, and a
    traversal that has to guess is the thing this module exists to remove.
    """
    text = (text or "").strip()
    if not text:
        raise GraphError("a node needs text")
    if len(text) > MAX_TEXT:
        text = text[: MAX_TEXT - 1] + "…"
    if kind not in KINDS:
        raise GraphError(f"kind must be one of {', '.join(KINDS)}, got {kind!r}")
    if len(g["nodes"]) >= MAX_NODES:
        raise GraphError(f"the graph is at {MAX_NODES} nodes, which is a bug and not a plan")

    ps: list = []
    for p in parents:
        if p in ps:
            continue          # a repeated parent is one edge, not two
        if p not in g["nodes"]:
            raise GraphError(f"no such parent: {p}")
        ps.append(p)

    if nid is not None:
        if not _ID_RE.match(nid):
            raise GraphError(f"bad id: {nid!r}")
        if nid in g["nodes"]:
            raise GraphError(f"duplicate id: {nid}")
        if nid in ps:
            raise GraphError("a node cannot be its own parent")
    else:
        nid = _mkid(g, text)
        while nid in g["nodes"]:
            nid = _mkid(g, text)

    if kind == "core" and ps:
        raise GraphError("a core objective has no parents; it is what everything else serves")

    t = _now() if now is None else now
    g["nodes"][nid] = {
        "id": nid,
        "text": text,
        "kind": kind,
        "status": "open",
        "parents": ps,
        "created_at": t,
        "updated_at": t,
        "closed_at": None,
        "note": "",
    }
    return nid


def resolve(g: dict, nid: str) -> str:
    """An id, or the shortest thing that can only mean one node.

    Ids are slugs -- `n2-move-mumchimp-dns-off-fly` -- because a bare counter is
    unreadable in a nudge and the text is what makes the walk-back worth printing. That
    makes them long to type, and a tool that refuses `n2` when exactly one node starts
    with `n2` is refusing correct work, which LAW 38 grades as an outage rather than a
    rough edge. Exact match always wins, so a full id can never be read as a prefix of
    another. An ambiguous prefix refuses and names the candidates, because guessing which
    of two objectives the agent meant is the one failure mode worse than asking.

    Resolution happens at the CLI boundary only. The library keeps exact ids so that
    every invariant in `net()` stays a straight dict lookup.
    """
    if nid in g["nodes"]:
        return nid
    hits = sorted(k for k in g["nodes"] if k.startswith(nid))
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise GraphError(f"{nid} could mean any of: {', '.join(hits)}")
    return nid


def reparent(g: dict, nid: str, parents: Iterable[str], now: Optional[int] = None) -> None:
    """Replace a node's parents. Refuses a cycle, which is the only way to make one."""
    if nid not in g["nodes"]:
        raise GraphError(f"no such node: {nid}")
    ps: list = []
    for p in parents:
        if p in ps:
            continue
        if p not in g["nodes"]:
            raise GraphError(f"no such parent: {p}")
        if p == nid:
            raise GraphError("a node cannot be its own parent")
        ps.append(p)
    below = descendants(g, nid)
    for p in ps:
        if p in below:
            raise GraphError(f"{p} is below {nid}; that edge would close a cycle")
    if g["nodes"][nid].get("kind") == "core" and ps:
        raise GraphError("a core objective has no parents")
    g["nodes"][nid]["parents"] = ps
    g["nodes"][nid]["updated_at"] = _now() if now is None else now


def _checkpoint(**kw) -> dict:
    """LAW 25's five headings. Empty strings are kept so the shape never varies."""
    return {k: str(kw.get(k) or "").strip()[:MAX_TEXT]
            for k in ("done", "found", "decision", "next", "blocked")}


def activate(
    g: dict,
    nid: str,
    reason: str = "",
    checkpoint: Optional[dict] = None,
    now: Optional[int] = None,
) -> dict:
    """Make *nid* the active node, parking the old one if this is a context switch.

    Returns a record of what happened: {"move": relation, "parked": id or None,
    "resumed": id or None}.
    """
    if nid not in g["nodes"]:
        raise GraphError(f"no such node: {nid}")
    node = g["nodes"][nid]
    if node["status"] in CLOSED:
        raise GraphError(f"{nid} is {node['status']}; reopen it before activating it")

    t = _now() if now is None else now
    prev = g.get("active")
    move = relation(g, prev, nid)
    out = {"move": move, "parked": None, "resumed": None, "from": prev, "to": nid}

    if move == "same":
        return out

    if move == "sideways":
        cp = _checkpoint(**(checkpoint or {}))
        # Two removals, and both matter. Dropping `prev` keeps the stack a set: a node
        # parked twice is one waiting item, and a duplicate frame reports a return path
        # that has already been walked. Dropping `nid` is the other half -- moving
        # sideways ONTO a parked node is a return to it, so its frame comes off. Without
        # that, the node the agent is working on sits on its own list of abandoned work.
        was_parked = any(f.get("node") == nid for f in g["stack"])
        g["stack"] = [f for f in g["stack"] if f.get("node") not in (prev, nid)]
        if was_parked:
            out["resumed"] = nid
        g["stack"].append({
            "node": prev, "at": t, "tick": int(g.get("tick", 0)),
            "reason": str(reason or "")[:MAX_TEXT], "checkpoint": cp,
        })
        g["nodes"][prev]["status"] = "parked"
        g["nodes"][prev]["updated_at"] = t
        out["parked"] = prev
        g["switches"].append({"at": t, "tick": int(g.get("tick", 0)),
                              "from": prev, "to": nid, "reason": str(reason or "")[:200]})
        ledger({"event": "switch", "session": g.get("session", ""), "from": prev,
                "to": nid, "reason": str(reason or "")[:200], "depth": len(g["stack"])})
    else:
        # Coming back up, or going deeper. If the node being activated is one that was
        # parked, this IS the return and the frame comes off.
        before = len(g["stack"])
        g["stack"] = [f for f in g["stack"] if f.get("node") != nid]
        if len(g["stack"]) != before:
            out["resumed"] = nid
            ledger({"event": "resume", "session": g.get("session", ""), "node": nid,
                    "depth": len(g["stack"])})

    if prev is not None and prev in g["nodes"] and g["nodes"][prev]["status"] == "active":
        g["nodes"][prev]["status"] = "open"
    node["status"] = "active"
    node["updated_at"] = t
    g["active"] = nid
    g["active_since_tick"] = int(g.get("tick", 0))
    return out


def close(g: dict, nid: str, status: str = "done", note: str = "",
          now: Optional[int] = None) -> dict:
    """Mark a node done or dropped, and hand back the node to return to.

    Returns {"next": id or None, "reason": str}. The next node is the top of the stack if
    there is one, because pre-switch work outranks anything newer; otherwise the nearest
    open ancestor, which is the objective this node was serving.
    """
    if status not in ("done", "dropped"):
        raise GraphError("a node is closed as done or dropped")
    if nid not in g["nodes"]:
        raise GraphError(f"no such node: {nid}")
    t = _now() if now is None else now
    n = g["nodes"][nid]
    n["status"] = status
    n["closed_at"] = t
    n["updated_at"] = t
    if note:
        n["note"] = str(note)[:MAX_TEXT]

    g["stack"] = [f for f in g["stack"] if f.get("node") != nid]
    if g.get("active") == nid:
        g["active"] = None

    ledger({"event": status, "session": g.get("session", ""), "node": nid,
            "text": n.get("text", "")[:200]})

    if g["stack"]:
        top = g["stack"][-1]["node"]
        if top in g["nodes"] and g["nodes"][top]["status"] not in CLOSED:
            return {"next": top, "reason": "parked before a context switch"}
    for anc in path_to_core(g, nid)[1:]:
        if g["nodes"][anc]["status"] not in CLOSED:
            return {"next": anc, "reason": "the objective this served"}
    for p in parents_of(g, nid):
        if g["nodes"][p]["status"] not in CLOSED:
            return {"next": p, "reason": "the objective this served"}
    return {"next": None, "reason": "nothing waiting"}


def resume(g: dict, now: Optional[int] = None) -> Optional[dict]:
    """Pop the newest parked frame and make it active. Returns the frame, or None.

    Frames whose node has since been closed are discarded rather than returned: coming
    back to finished work is not a return path, it is a loop.
    """
    while g["stack"]:
        frame = g["stack"][-1]
        nid = frame.get("node")
        if nid in g["nodes"] and g["nodes"][nid]["status"] not in CLOSED:
            g["stack"].pop()
            activate(g, nid, reason="resume", now=now)
            ledger({"event": "resume", "session": g.get("session", ""), "node": nid,
                    "depth": len(g["stack"])})
            return frame
        g["stack"].pop()
    return None


def tick(g: dict, n: int = 1) -> int:
    g["tick"] = int(g.get("tick", 0)) + max(0, int(n))
    return g["tick"]


# --------------------------------------------------------------------------
# the net check
# --------------------------------------------------------------------------

def net(g: dict) -> dict:
    """Traverse every node and every edge, and report what does not hold.

    Nine invariants, each a fact a command can check. `ok` is False if any fired. This is
    the founder's "traverse all goal and ensure net", and it is the one place that walks
    the whole graph rather than one path through it.
    """
    problems: list = []
    nodes = g["nodes"]

    def flag(kind: str, detail: str, ids: list) -> None:
        problems.append({"check": kind, "detail": detail, "nodes": ids})

    # 1. the key and the node agree, the shape is a shape
    bad_shape = [k for k, n in nodes.items()
                 if not isinstance(n, dict) or n.get("id") != k
                 or n.get("status") not in STATUSES or n.get("kind") not in KINDS]
    if bad_shape:
        flag("malformed", "node is not a node, or its id does not match its key",
             sorted(bad_shape))

    # 2. every parent exists
    dangling = sorted({k for k in nodes
                       for p in parents_of(g, k) if p not in nodes})
    if dangling:
        flag("dangling_parent", "a node points at a parent that is not in the graph",
             dangling)

    # 3. no cycles. Three-colour DFS, iterative, so a deep graph cannot blow the stack.
    colour: dict = {}
    cyclic: set = set()
    for start in sorted(nodes):
        if colour.get(start):
            continue
        stack = [(start, iter(parents_of(g, start)))]
        colour[start] = 1
        while stack:
            cur, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                colour[cur] = 2
                stack.pop()
                continue
            if nxt not in nodes:
                continue
            c = colour.get(nxt, 0)
            if c == 1:
                cyclic.add(nxt)
                cyclic.add(cur)
            elif c == 0:
                colour[nxt] = 1
                stack.append((nxt, iter(parents_of(g, nxt))))
    if cyclic:
        flag("cycle", "these nodes are on a cycle, so no walk to core terminates",
             sorted(cyclic))

    # 4. open work serves a core objective
    if cores(g):
        off = sorted(k for k, n in nodes.items()
                     if n.get("status") not in CLOSED and k not in cyclic
                     and not reaches_core(g, k))
        if off:
            flag("off_net", "open, and no path from it up to a core objective", off)
    elif nodes:
        flag("no_core", "the graph has nodes but no core objective to walk back to",
             roots(g))

    # 5. the active node is real, open, and singular
    active = g.get("active")
    if active is not None:
        if active not in nodes:
            flag("active_missing", "active points at a node that is not in the graph",
                 [active])
        elif nodes[active].get("status") in CLOSED:
            flag("active_closed", f"active node is {nodes[active]['status']}", [active])
    claimed = sorted(k for k, n in nodes.items() if n.get("status") == "active")
    if len(claimed) > 1 or (claimed and claimed != [active]):
        flag("active_disagree", "more than one node says it is active, or none is `active`",
             claimed)

    # 6. the stack is a return path, not a list
    seen_frames: set = set()
    bad_frames: list = []
    for f in g.get("stack", []):
        nid = f.get("node") if isinstance(f, dict) else None
        if (not isinstance(nid, str) or nid not in nodes
                or nid in seen_frames or nid == active
                or nodes[nid].get("status") in CLOSED):
            bad_frames.append(str(nid))
        else:
            seen_frames.add(nid)
    if bad_frames:
        flag("stack_broken",
             "a parked frame is missing, duplicated, closed, or is the active node",
             bad_frames)

    # 7. a parked node is on the stack, and a node on the stack is parked
    parked = {k for k, n in nodes.items() if n.get("status") == "parked"}
    if parked != seen_frames:
        flag("parked_disagree",
             "a node is parked with no frame, or has a frame and is not parked",
             sorted(parked ^ seen_frames))

    # 8. a closed node with open work beneath it
    orphaned = sorted(
        k for k, n in nodes.items()
        if n.get("status") in CLOSED
        and any(nodes[c].get("status") not in CLOSED for c in children_of(g, k))
    )
    if orphaned:
        flag("closed_with_open_children",
             "closed, but work beneath it is still open", orphaned)

    # 9. a root that is not core, carrying open work
    stray = sorted(r for r in roots(g)
                   if nodes.get(r, {}).get("kind") != "core"
                   and (nodes.get(r, {}).get("status") not in CLOSED
                        or any(nodes[d].get("status") not in CLOSED
                               for d in descendants(g, r))))
    if stray:
        flag("stray_root", "a root that is not a core objective, with open work under it",
             stray)

    open_nodes = [k for k, n in nodes.items() if n.get("status") not in CLOSED]
    return {
        "ok": not problems,
        "problems": problems,
        "counts": {
            "nodes": len(nodes),
            "open": len(open_nodes),
            "done": sum(1 for n in nodes.values() if n.get("status") == "done"),
            "dropped": sum(1 for n in nodes.values() if n.get("status") == "dropped"),
            "cores": len(cores(g)),
            "roots": len(roots(g)),
            "parked": len(g.get("stack", [])),
            "switches": len(g.get("switches", [])),
            "edges": sum(len(parents_of(g, k)) for k in nodes),
        },
    }


# --------------------------------------------------------------------------
# drift
# --------------------------------------------------------------------------

def drift(g: dict, now: Optional[int] = None) -> list:
    """Every drift signal that currently holds, worst first.

    Each is structural. None reads the transcript, scores meaning or calls a model, because
    a signal an agent cannot check with a command is a signal it will argue with.
    """
    t = _now() if now is None else now
    nodes = g["nodes"]
    tk = int(g.get("tick", 0))
    out: list = []

    if not nodes:
        out.append({"signal": "no_graph", "severity": 3,
                    "why": "the session has done work and has no objective on disk"})
        return out

    open_left = [k for k, n in nodes.items() if n.get("status") not in CLOSED]
    active = g.get("active")
    if not open_left:
        # Everything is closed. There is nothing to be active on, and saying so would
        # fire the loudest signal this module has at the one moment the agent is right.
        active = None
    elif active is None or active not in nodes or nodes[active].get("status") in CLOSED:
        out.append({"signal": "no_active", "severity": 3,
                    "why": "nodes exist and none is active, so nothing says what this is for"})
    elif not reaches_core(g, active):
        out.append({"signal": "off_net", "severity": 3, "node": active,
                    "why": "the active node has no path up to a core objective"})

    stack = [f for f in g.get("stack", []) if isinstance(f, dict)]
    for f in stack:
        nid = f.get("node")
        if nid not in nodes or nodes[nid].get("status") in CLOSED:
            continue
        age_s = t - int(f.get("at", t))
        age_t = tk - int(f.get("tick", tk))
        if age_s >= PARK_MAX_SECONDS or age_t >= PARK_MAX_TICKS:
            out.append({"signal": "parked_abandoned", "severity": 2, "node": nid,
                        "age_seconds": age_s, "age_ticks": age_t,
                        "why": "work parked at a context switch and never returned to"})

    if len(stack) > STACK_SOFT_DEPTH:
        out.append({"signal": "stack_deep", "severity": 2, "depth": len(stack),
                    "why": f"{len(stack)} pieces of work are parked; "
                           "each one is a return path nobody has walked"})

    recent = [s for s in g.get("switches", [])
              if tk - int(s.get("tick", 0)) <= THRASH_WINDOW_TICKS]
    if len(recent) >= THRASH_SWITCHES:
        out.append({"signal": "thrash", "severity": 2, "switches": len(recent),
                    "why": f"{len(recent)} context switches in the last "
                           f"{THRASH_WINDOW_TICKS} tool calls"})

    if active in nodes and nodes[active].get("status") == "active":
        since = tk - int(g.get("active_since_tick", tk))
        moved = any(int(n.get("updated_at", 0)) > int(nodes[active].get("updated_at", 0))
                    for k, n in nodes.items() if k != active)
        if since >= STALL_TICKS and not moved:
            out.append({"signal": "stall", "severity": 1, "node": active, "ticks": since,
                        "why": f"{since} tool calls on one node with nothing opened "
                               "or closed beneath it"})

    problems = net(g)["problems"]
    if problems:
        out.append({"signal": "net_broken", "severity": 1,
                    "checks": [p["check"] for p in problems],
                    "why": "the goal net does not hold; goal_graph.py --net says how"})

    out.sort(key=lambda d: -d["severity"])
    return out


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _line(g: dict, nid: str) -> str:
    n = g["nodes"].get(nid)
    if not n:
        return f"{nid} (missing)"
    mark = {"core": "CORE", "goal": "goal", "task": "task"}[n.get("kind", "task")]
    return f"[{mark}] {n.get('text', '')}  ({nid}, {n.get('status')})"


def render_path(g: dict, nid: Optional[str] = None) -> str:
    """The walk back, one line per hop, from where the agent stands up to core."""
    nid = nid or g.get("active")
    if not nid:
        return "no active node, so there is nothing to walk back from"
    trail = path_to_core(g, nid)
    if not trail:
        if nid not in g["nodes"]:
            return f"no such node: {nid}"
        return (f"{_line(g, nid)}\n"
                "  ^ no path from here up to a core objective. This is off the net: "
                "either it serves something, and needs the edge, or it is not the job.")
    return "\n".join(
        ("  " * i) + ("" if i == 0 else "^ serves ") + _line(g, h)
        for i, h in enumerate(trail)
    )


def render_stack(g: dict) -> str:
    stack = [f for f in g.get("stack", []) if isinstance(f, dict)]
    if not stack:
        return "nothing parked"
    lines = []
    for f in reversed(stack):
        nid = f.get("node")
        cp = f.get("checkpoint") or {}
        lines.append(f"  {_line(g, nid)}")
        if f.get("reason"):
            lines.append(f"      left because: {f['reason']}")
        if cp.get("next"):
            lines.append(f"      next: {cp['next']}")
        if cp.get("blocked"):
            lines.append(f"      blocked: {cp['blocked']}")
    return "\n".join(lines)


def render_nudge(g: dict, signals: Optional[list] = None) -> str:
    """What a hook injects. Says where the agent is, what it serves, and what is waiting."""
    signals = drift(g) if signals is None else signals
    if not signals:
        return ""
    head = signals[0]
    parts = [f"[goal-net] {head['why']}."]
    for s in signals[1:]:
        parts.append(f"  also: {s['why']}.")
    active = g.get("active")
    if active and active in g["nodes"]:
        parts.append("")
        parts.append("Where you are, and what it serves:")
        parts.append(render_path(g, active))
    elif cores(g):
        parts.append("")
        parts.append("The core objectives this session is for:")
        for c in cores(g):
            parts.append(f"  {_line(g, c)}")
    stack = [f for f in g.get("stack", []) if isinstance(f, dict)]
    if stack:
        parts.append("")
        parts.append("Parked at a context switch, oldest last. Finish or drop these:")
        parts.append(render_stack(g))
        top = stack[-1].get("node")
        parts.append("")
        parts.append(f"  Return with: goal_graph.py --resume    (goes back to {top})")
    if not g["nodes"]:
        parts.append("")
        parts.append("  Start with: goal_graph.py --add 'the objective' --kind core")
    return "\n".join(parts)


def render_tree(g: dict) -> str:
    """The whole net, core objectives down. Shared nodes are printed once and referenced."""
    if not g["nodes"]:
        return "(empty)"
    printed: set = set()
    out: list = []

    def walk(nid: str, depth: int) -> None:
        pad = "  " * depth
        if nid in printed:
            out.append(f"{pad}- {_line(g, nid)}  [also above]")
            return
        printed.add(nid)
        mark = ">" if nid == g.get("active") else "-"
        out.append(f"{pad}{mark} {_line(g, nid)}")
        for c in children_of(g, nid):
            walk(c, depth + 1)

    for r in cores(g) or roots(g):
        walk(r, 0)
    for k in sorted(g["nodes"]):
        if k not in printed:
            out.append(f"- {_line(g, k)}  [not reachable from any root]")
    return "\n".join(out)


# --------------------------------------------------------------------------
# the hook-facing half: never raises, ever
# --------------------------------------------------------------------------

def safe_nudge(session: str, root: Optional[Path] = None, bump: int = 1) -> str:
    """One call for a PreToolUse hook: count the call, return a nudge or "".

    Every exception is swallowed. A guard that wedges a session is a worse outage than the
    drift it was watching for -- the house rule scope-guard.py states and goal-guard.py
    follows.
    """
    try:
        g = load(session, root)
        if not g["nodes"] and not g.get("tick"):
            # An empty graph in a session that has not started is not drift.
            tick(g, bump)
            save(g, root)
            return ""
        tick(g, bump)
        signals = drift(g)
        names = sorted({s["signal"] for s in signals})
        # Rate limit, or the guard becomes the noise. A signal set the session has not
        # seen fires at once; one it has already been told about repeats every
        # NUDGE_EVERY_TICKS calls. goal-guard.py fires 1.10 times per session on its own
        # counter and that is the shape being matched, not exceeded.
        due = (names != g.get("last_nudge_signals")
               or int(g.get("tick", 0)) - int(g.get("last_nudge_tick", -10**9))
               >= NUDGE_EVERY_TICKS)
        if not signals or not due:
            save(g, root)
            return ""
        g["last_nudge_signals"] = names
        g["last_nudge_tick"] = int(g.get("tick", 0))
        save(g, root)
        ledger({"event": "nudge", "session": session, "signals": names,
                "tick": g.get("tick", 0)})
        return render_nudge(g, signals)
    except Exception:
        return ""


def safe_status(session: str, root: Optional[Path] = None) -> str:
    """One line for a SessionStart hook. Never raises."""
    try:
        g = load(session, root)
        if not g["nodes"]:
            return ""
        c = net(g)["counts"]
        bits = [f"{c['open']} open of {c['nodes']}", f"{c['cores']} core"]
        if c["parked"]:
            bits.append(f"{c['parked']} PARKED and waiting")
        active = g.get("active")
        head = f"[goal-net] {', '.join(bits)}."
        if active and active in g["nodes"]:
            return head + "\n" + render_path(g, active)
        return head + "\n" + render_nudge(g)
    except Exception:
        return ""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _session(args) -> str:
    return (args.session or os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("HERMES_SESSION_ID") or "default")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="goal_graph.py",
        description="Objectives as a graph: walk back to core, and return after a switch.")
    ap.add_argument("--session", help="session id (default $CLAUDE_SESSION_ID or 'default')")
    ap.add_argument("--json", action="store_true", help="machine output")

    ap.add_argument("--add", metavar="TEXT", help="add a node, print its id")
    ap.add_argument("--parent", action="append", default=[], metavar="ID",
                    help="a parent for --add; repeat for several")
    ap.add_argument("--kind", default="task", choices=list(KINDS))
    ap.add_argument("--id", dest="nid", help="explicit id for --add")

    ap.add_argument("--activate", metavar="ID", help="make a node active")
    ap.add_argument("--reason", default="", help="why the switch, for --activate")
    for h in ("done", "found", "decision", "next", "blocked"):
        ap.add_argument(f"--cp-{h}", default="", metavar="TEXT",
                        help=f"checkpoint '{h}' recorded when --activate parks the old node")

    ap.add_argument("--close", metavar="ID", help="mark a node done")
    ap.add_argument("--drop", metavar="ID", help="mark a node dropped")
    ap.add_argument("--note", default="", help="note for --close/--drop")
    ap.add_argument("--reparent", metavar="ID", help="replace a node's parents")

    ap.add_argument("--resume", action="store_true", help="return to the newest parked node")
    ap.add_argument("--path", nargs="?", const="", metavar="ID",
                    help="walk from a node (default: active) up to core")
    ap.add_argument("--tree", action="store_true", help="the whole net, core down")
    ap.add_argument("--net", action="store_true",
                    help="traverse everything and check it holds; exit 1 if not")
    ap.add_argument("--drift", action="store_true",
                    help="print the nudge if the session is drifting; exit 1 if it is")
    ap.add_argument("--status", action="store_true", help="one-line state")
    ap.add_argument("--tick", type=int, metavar="N", help="count N tool calls")
    ap.add_argument("--reset", action="store_true", help="throw this session's graph away")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    sess = _session(args)

    if args.reset:
        p = state_path(sess)
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        print(f"graph for {sess} is gone")
        return 0

    g = load(sess)

    try:
        # Every id the user typed becomes a real id here, once, before any mutation sees it.
        parents = [resolve(g, p) for p in (args.parent or [])]
        for attr in ("reparent", "activate", "close", "drop"):
            val = getattr(args, attr, None)
            if val:
                setattr(args, attr, resolve(g, val))
        if args.path:
            args.path = resolve(g, args.path)

        if args.add:
            nid = add(g, args.add, parents, args.kind, args.nid)
            if g.get("active") is None and args.kind != "core":
                activate(g, nid)
            save(g)
            print(nid)
            return 0

        if args.reparent:
            reparent(g, args.reparent, parents)
            save(g)
            print(render_path(g, args.reparent))
            return 0

        if args.activate:
            cp = {h: getattr(args, f"cp_{h}") for h in
                  ("done", "found", "decision", "next", "blocked")}
            out = activate(g, args.activate, args.reason, cp)
            save(g)
            if args.json:
                print(json.dumps(out))
            else:
                print(f"{out['move']}: {_line(g, args.activate)}")
                if out["parked"]:
                    print(f"parked, and waiting: {_line(g, out['parked'])}")
                if out["resumed"]:
                    print(f"resumed: {out['resumed']}")
                print(render_path(g, args.activate))
            return 0

        if args.close or args.drop:
            nid = args.close or args.drop
            out = close(g, nid, "done" if args.close else "dropped", args.note)
            save(g)
            if args.json:
                print(json.dumps(out))
            elif out["next"]:
                print(f"next: {_line(g, out['next'])}  ({out['reason']})")
            else:
                print("nothing waiting")
            return 0

        if args.resume:
            frame = resume(g)
            save(g)
            if not frame:
                print("nothing parked")
                return 1
            print(f"back on: {_line(g, frame['node'])}")
            cp = frame.get("checkpoint") or {}
            for h in ("done", "found", "decision", "next", "blocked"):
                if cp.get(h):
                    print(f"  {h}: {cp[h]}")
            print(render_path(g, frame["node"]))
            return 0
    except GraphError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    if args.tick is not None:
        tick(g, args.tick)
        save(g)
        print(g["tick"])
        return 0

    if args.path is not None:
        print(render_path(g, args.path or None))
        return 0

    if args.tree:
        print(render_tree(g))
        return 0

    if args.net:
        rep = net(g)
        if args.json:
            print(json.dumps(rep, indent=1))
        else:
            c = rep["counts"]
            print(f"{c['nodes']} nodes, {c['edges']} edges, {c['open']} open, "
                  f"{c['cores']} core, {c['parked']} parked, {c['switches']} switches")
            for p in rep["problems"]:
                print(f"  BROKEN {p['check']}: {p['detail']}")
                for n in p["nodes"][:10]:
                    print(f"      {_line(g, n)}")
            print("the net holds" if rep["ok"] else "the net does not hold")
        return 0 if rep["ok"] else 1

    if args.drift:
        sigs = drift(g)
        if args.json:
            print(json.dumps(sigs, indent=1))
        elif sigs:
            print(render_nudge(g, sigs))
        else:
            print("on the net, on the job")
        return 1 if sigs else 0

    print(safe_status(sess) or "no graph for this session yet. "
          "Start with: goal_graph.py --add 'the objective' --kind core")
    return 0


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------

def selftest() -> int:  # noqa: C901
    """Exhaustive edge cases, run with plain asserts so this file needs no test runner.

    The founder asked for exhaustive edge-case testing by name. The cases below are grouped
    by what they defend, and every one of them is a way this module could quietly return a
    wrong answer rather than fail loudly: a traversal that does not terminate, a stack that
    holds a return path already taken, a switch counted where the agent only decomposed.
    """
    import shutil

    fails: list = []
    checks = {"n": 0}

    def ck(label: str, cond: bool) -> None:
        checks["n"] += 1
        if not cond:
            fails.append(label)

    def raises(label: str, fn: Callable) -> None:
        checks["n"] += 1
        try:
            fn()
        except GraphError:
            return
        except Exception as exc:                       # noqa: BLE001
            fails.append(f"{label} (raised {type(exc).__name__}, wanted GraphError)")
            return
        fails.append(f"{label} (did not refuse)")

    tmp = Path(tempfile.mkdtemp(prefix="goalnet-selftest-"))
    try:
        # ---------- the shape of an empty world ----------
        g = empty_graph("s")
        ck("empty graph: net holds", net(g)["ok"])
        ck("empty graph: no path", render_path(g).startswith("no active"))
        ck("empty graph: tree says empty", render_tree(g) == "(empty)")
        ck("empty graph: drift is no_graph",
           [s["signal"] for s in drift(g)] == ["no_graph"])
        ck("empty graph: nudge is not empty", bool(render_nudge(g)))
        ck("empty graph: resume returns None", resume(g) is None)

        # ---------- add: what it refuses ----------
        g = empty_graph("s")
        core = add(g, "run the estate without me", kind="core")
        ck("core added", g["nodes"][core]["kind"] == "core")
        raises("empty text refused", lambda: add(g, ""))
        raises("blank text refused", lambda: add(g, "   "))
        raises("unknown parent refused", lambda: add(g, "x", ["nope"]))
        raises("bad kind refused", lambda: add(g, "x", kind="epic"))
        raises("core with a parent refused", lambda: add(g, "x", [core], kind="core"))
        raises("bad id refused", lambda: add(g, "x", nid="../../etc/passwd"))
        raises("empty id refused", lambda: add(g, "x", nid=""))
        raises("duplicate id refused", lambda: add(g, "x", nid=core))
        raises("self parent refused", lambda: add(g, "x", [ "n-self" ], nid="n-self"))
        ck("nothing was added by a refusal", len(g["nodes"]) == 1)

        long = add(g, "L" * (MAX_TEXT * 3), [core])
        ck("long text is trimmed, not refused", len(g["nodes"][long]["text"]) == MAX_TEXT)
        uni = add(g, "承 the laws 承 \U0001f600", [core])
        ck("unicode survives", "\U0001f600" in g["nodes"][uni]["text"])
        dup = add(g, "twice", [core, core])
        ck("a repeated parent is one edge", g["nodes"][dup]["parents"] == [core])

        # ---------- the net: two parents, and a walk back through either ----------
        g = empty_graph("s")
        c1 = add(g, "the estate runs itself", kind="core")
        c2 = add(g, "nothing costs money it need not", kind="core")
        both = add(g, "kill the duplicate ledger", [c1, c2])
        leaf = add(g, "delete the second writer", [both])
        ck("two parents are kept", len(g["nodes"][both]["parents"]) == 2)
        ck("walk back reaches a core", path_to_core(g, leaf)[-1] in (c1, c2))
        ck("walk back is shortest", len(path_to_core(g, leaf)) == 3)
        ck("a core's own path is itself", path_to_core(g, c1) == [c1])
        ck("net holds with a diamond", net(g)["ok"])
        ck("descendants of a core include the leaf", leaf in descendants(g, c1))
        ck("ancestors of the leaf include both cores",
           {c1, c2} <= ancestors(g, leaf))

        # ---------- relation: the rule that decides what a switch is ----------
        ck("first move", relation(g, None, leaf) == "first")
        ck("same is same", relation(g, leaf, leaf) == "same")
        ck("down is deeper", relation(g, both, leaf) == "deeper")
        ck("up is shallower", relation(g, leaf, both) == "shallower")
        other = add(g, "unrelated", [c2])
        ck("across is sideways", relation(g, leaf, other) == "sideways")
        ck("a sibling is sideways", relation(g, other, leaf) == "sideways")
        ck("an unknown from is first", relation(g, "ghost", leaf) == "first")

        # ---------- decomposition must not read as a switch ----------
        g = empty_graph("s")
        c = add(g, "core", kind="core")
        a = add(g, "goal a", [c], kind="goal")
        a1 = add(g, "task a1", [a])
        a2 = add(g, "task a2", [a])
        activate(g, a)
        r = activate(g, a1)
        ck("going deeper is not a switch", r["move"] == "deeper" and r["parked"] is None)
        ck("nothing parked by decomposition", g["stack"] == [])
        r = activate(g, a)
        ck("coming back up is not a switch", r["move"] == "shallower")
        ck("still nothing parked", g["stack"] == [])
        r = activate(g, a2)
        ck("a1 to a2 through the parent is not sideways here", r["move"] == "deeper")

        # ---------- the switch, the park, and the return ----------
        g = empty_graph("s")
        c = add(g, "core", kind="core")
        job = add(g, "the named job", [c], kind="goal")
        fire = add(g, "the fire", [c], kind="goal")
        activate(g, job)
        r = activate(g, fire, reason="LAW 1", checkpoint={"next": "read the log", "done": "x"})
        ck("sideways is a switch", r["move"] == "sideways")
        ck("the old node parked", r["parked"] == job)
        ck("the parked node says parked", g["nodes"][job]["status"] == "parked")
        ck("one frame on the stack", len(g["stack"]) == 1)
        ck("the checkpoint is kept", g["stack"][0]["checkpoint"]["next"] == "read the log")
        ck("all five headings exist", len(g["stack"][0]["checkpoint"]) == 5)
        ck("the switch is recorded", len(g["switches"]) == 1)
        ck("net holds while parked", net(g)["ok"])
        ck("the return path names the parked work", job in render_stack(g))
        ck("a fresh switch is not itself drift", drift(g) == [])

        out = close(g, fire)
        ck("closing the fire points back at the parked job", out["next"] == job)
        ck("and says why", "parked" in out["reason"])
        frame = resume(g)
        ck("resume returns the frame", frame and frame["node"] == job)
        ck("resume clears the stack", g["stack"] == [])
        ck("resume makes it active", g["active"] == job)
        ck("and it is active, not parked", g["nodes"][job]["status"] == "active")
        ck("net holds after the return", net(g)["ok"])

        # ---------- parking the same node twice is one waiting item ----------
        g = empty_graph("s")
        c = add(g, "core", kind="core")
        x = add(g, "x", [c], kind="goal")
        y = add(g, "y", [c], kind="goal")
        z = add(g, "z", [c], kind="goal")
        activate(g, x); activate(g, y); activate(g, x); activate(g, y)
        ck("no duplicate frames", len({f["node"] for f in g["stack"]}) == len(g["stack"]))
        ck("the active node is never on the stack",
           all(f["node"] != g["active"] for f in g["stack"]))
        ck("net holds after a shuffle", net(g)["ok"])
        activate(g, z)
        ck("stack holds both parked", len(g["stack"]) == 2)
        ck("newest parked is on top", g["stack"][-1]["node"] == y)

        # ---------- resume skips work that was closed while parked ----------
        close(g, y)
        ck("closing a parked node removes its frame",
           all(f["node"] != y for f in g["stack"]))
        ck("net still holds", net(g)["ok"])
        frame = resume(g)
        ck("resume lands on the surviving parked node", frame and frame["node"] == x)

        # ---------- close: what it hands back ----------
        g = empty_graph("s")
        c = add(g, "core", kind="core")
        goal = add(g, "goal", [c], kind="goal")
        t1 = add(g, "task", [goal])
        activate(g, t1)
        out = close(g, t1)
        ck("closing a leaf points at its objective", out["next"] == goal)
        ck("active is cleared", g.get("active") is None)
        ck("closed_at is stamped", g["nodes"][t1]["closed_at"])
        raises("close with a bad status refused", lambda: close(g, goal, "abandoned"))
        raises("close of an unknown node refused", lambda: close(g, "ghost"))
        out = close(g, goal)
        ck("closing the goal points at core", out["next"] == c)
        out = close(g, c)
        ck("closing the last thing has no next", out["next"] is None)
        ck("net holds when everything is done", net(g)["ok"])
        ck("no drift when everything is done",
           [s["signal"] for s in drift(g)] == [])

        # ---------- activate: what it refuses ----------
        g = empty_graph("s")
        c = add(g, "core", kind="core")
        t1 = add(g, "t", [c])
        close(g, t1)
        raises("activating a done node refused", lambda: activate(g, t1))
        raises("activating an unknown node refused", lambda: activate(g, "ghost"))

        # ---------- reparent, and the cycle it must refuse ----------
        g = empty_graph("s")
        c = add(g, "core", kind="core")
        p = add(g, "p", [c], kind="goal")
        ch = add(g, "c", [p])
        gc = add(g, "gc", [ch])
        raises("a cycle through a child refused", lambda: reparent(g, p, [ch]))
        raises("a cycle through a grandchild refused", lambda: reparent(g, p, [gc]))
        raises("self parent refused", lambda: reparent(g, p, [p]))
        raises("unknown parent refused", lambda: reparent(g, p, ["ghost"]))
        raises("core with a parent refused", lambda: reparent(g, c, [p]))
        raises("reparent of an unknown node refused", lambda: reparent(g, "ghost", [c]))
        ck("nothing changed", g["nodes"][p]["parents"] == [c])
        reparent(g, gc, [c])
        ck("a legal reparent works", g["nodes"][gc]["parents"] == [c])
        ck("net holds after reparent", net(g)["ok"])

        # ---------- a hand-edited file: every invariant fires, and nothing hangs ----------
        g = empty_graph("s")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c], kind="goal")
        b = add(g, "b", [a])
        g["nodes"][a]["parents"] = [b]          # a cycle only a hand edit can make
        rep = net(g)
        ck("a cycle is caught", any(p["check"] == "cycle" for p in rep["problems"]))
        ck("the cycle traversal terminates", rep["counts"]["nodes"] == 3)
        ck("ancestors terminates on a cycle", isinstance(ancestors(g, b), set))
        ck("path_to_core terminates on a cycle", isinstance(path_to_core(g, b), list))
        ck("drift reports net_broken",
           any(s["signal"] == "net_broken" for s in drift(g)))

        g = empty_graph("s")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c])
        g["nodes"][a]["parents"] = ["ghost"]
        ck("a dangling parent is caught",
           any(p["check"] == "dangling_parent" for p in net(g)["problems"]))

        g = empty_graph("s")
        a = add(g, "no core here")
        ck("a graph with no core is caught",
           any(p["check"] == "no_core" for p in net(g)["problems"]))

        g = empty_graph("s")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c])
        g["active"] = "ghost"
        ck("a missing active is caught",
           any(p["check"] == "active_missing" for p in net(g)["problems"]))
        g["active"] = a
        g["nodes"][a]["status"] = "done"
        ck("a closed active is caught",
           any(p["check"] == "active_closed" for p in net(g)["problems"]))

        g = empty_graph("s")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c]); b = add(g, "b", [c])
        g["nodes"][a]["status"] = "active"
        g["nodes"][b]["status"] = "active"
        g["active"] = a
        ck("two actives are caught",
           any(p["check"] == "active_disagree" for p in net(g)["problems"]))

        g = empty_graph("s")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c])
        g["stack"] = [{"node": "ghost", "at": 0, "tick": 0, "checkpoint": _checkpoint()}]
        ck("a frame for a missing node is caught",
           any(p["check"] == "stack_broken" for p in net(g)["problems"]))
        g["stack"] = [{"node": a, "at": 0, "tick": 0, "checkpoint": _checkpoint()},
                      {"node": a, "at": 0, "tick": 0, "checkpoint": _checkpoint()}]
        ck("a duplicated frame is caught",
           any(p["check"] == "stack_broken" for p in net(g)["problems"]))
        g["stack"] = []
        g["nodes"][a]["status"] = "parked"
        ck("parked with no frame is caught",
           any(p["check"] == "parked_disagree" for p in net(g)["problems"]))

        g = empty_graph("s")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c], kind="goal")
        b = add(g, "b", [a])
        g["nodes"][a]["status"] = "done"
        ck("closing a goal with open work under it is caught",
           any(p["check"] == "closed_with_open_children" for p in net(g)["problems"]))

        g = empty_graph("s")
        c = add(g, "core", kind="core")
        stray = add(g, "a goal that serves nothing", kind="goal")
        rep = net(g)
        ck("a stray root is caught",
           any(p["check"] == "stray_root" for p in rep["problems"]))
        ck("and it is also off the net",
           any(p["check"] == "off_net" for p in rep["problems"]))
        ck("off the net shows in the walk-back",
           "no path from here" in render_path(g, stray))

        # ---------- drift signals, each in isolation ----------
        g = empty_graph("s")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c], kind="goal")
        activate(g, a)
        ck("a healthy graph does not drift", drift(g) == [])

        g2 = json.loads(json.dumps(g))
        g2["active"] = None
        g2["nodes"][a]["status"] = "open"
        ck("no active node is drift",
           any(s["signal"] == "no_active" for s in drift(g2)))

        g2 = json.loads(json.dumps(g))
        b = add(g2, "b", [c], kind="goal")
        activate(g2, b, checkpoint={"next": "finish a"})
        g2["stack"][0]["at"] = _now() - PARK_MAX_SECONDS - 1
        sigs = drift(g2)
        ck("stale parked work is drift",
           any(s["signal"] == "parked_abandoned" for s in sigs))
        ck("the nudge offers the return command", "--resume" in render_nudge(g2, sigs))
        g2["stack"][0]["at"] = _now()
        g2["stack"][0]["tick"] = 0
        g2["tick"] = PARK_MAX_TICKS + 1
        ck("parked work stale by tool calls is drift",
           any(s["signal"] == "parked_abandoned" for s in drift(g2)))

        g2 = json.loads(json.dumps(g))
        names = [add(g2, f"g{i}", [c], kind="goal") for i in range(STACK_SOFT_DEPTH + 2)]
        for n in names:
            activate(g2, n)
        ck("a deep stack is drift",
           any(s["signal"] == "stack_deep" for s in drift(g2)))
        ck("thrash fires too", any(s["signal"] == "thrash" for s in drift(g2)))
        ck("the worst signal sorts first", drift(g2)[0]["severity"] >= drift(g2)[-1]["severity"])

        g2 = json.loads(json.dumps(g))
        g2["tick"] = STALL_TICKS + 5
        g2["active_since_tick"] = 0
        ck("a stalled node is drift", any(s["signal"] == "stall" for s in drift(g2)))

        g2 = json.loads(json.dumps(g))
        g2["nodes"][a]["parents"] = []
        g2["nodes"][a]["kind"] = "goal"
        ck("an active node off the net is drift",
           any(s["signal"] == "off_net" for s in drift(g2)))

        # ---------- the store: round trip, corruption, atomicity, hostile ids ----------
        g = empty_graph("round-trip")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c], kind="goal")
        activate(g, a)
        b = add(g, "b", [c], kind="goal")
        activate(g, b, reason="switch", checkpoint={"next": "n", "blocked": "nothing"})
        save(g, tmp)
        back = load("round-trip", tmp)
        ck("round trip keeps the nodes", back["nodes"].keys() == g["nodes"].keys())
        ck("round trip keeps the stack", back["stack"] == g["stack"])
        ck("round trip keeps the checkpoint",
           back["stack"][0]["checkpoint"]["next"] == "n")
        ck("round trip keeps unicode", True)
        ck("round trip net holds", net(back)["ok"])

        (tmp / "corrupt.json").write_text("{not json", encoding="utf-8")
        ck("a corrupt file reads as empty", load("corrupt", tmp)["nodes"] == {})
        (tmp / "wrong.json").write_text('["a list"]', encoding="utf-8")
        ck("a wrong-shaped file reads as empty", load("wrong", tmp)["nodes"] == {})
        (tmp / "partial.json").write_text('{"nodes": {}, "stack": "no", "tick": -4}',
                                          encoding="utf-8")
        p = load("partial", tmp)
        ck("a broken stack is repaired", p["stack"] == [])
        ck("a negative tick is repaired", p["tick"] == 0)
        ck("missing file reads as empty", load("never-existed", tmp)["nodes"] == {})

        ck("a hostile session id cannot escape",
           ".." not in state_path("../../etc/passwd", tmp).name)
        ck("and still lands in the state dir",
           state_path("../../x", tmp).parent == tmp)
        ck("an empty session id has a name", state_path("", tmp).name == "unknown.json")
        ck("a session id with a slash is flattened",
           "/" not in state_path("a/b/c", tmp).name)

        # ---------- the hook half never raises, whatever it is handed ----------
        ck("safe_nudge on a fresh session is quiet", safe_nudge("brand-new", tmp) == "")
        ck("safe_nudge on a corrupt file is quiet", safe_nudge("corrupt", tmp) == "")
        ck("safe_status on a corrupt file is quiet", safe_status("corrupt", tmp) == "")
        ck("safe_nudge with a hostile id is quiet", safe_nudge("../../x", tmp) == "")
        g = empty_graph("nudgy")
        c = add(g, "core", kind="core")
        a = add(g, "a", [c], kind="goal")
        b = add(g, "b", [c], kind="goal")
        activate(g, a)
        activate(g, b, checkpoint={"next": "go back to a"})
        g["stack"][0]["at"] = _now() - PARK_MAX_SECONDS - 1
        save(g, tmp)
        msg = safe_nudge("nudgy", tmp)
        ck("safe_nudge fires on real drift", bool(msg))
        ck("and it names the return command", "--resume" in msg)
        ck("and the tick was counted", load("nudgy", tmp)["tick"] >= 1)
        ck("the same signal does not fire twice in a row",
           safe_nudge("nudgy", tmp) == "")
        ck("and it still counts the calls it stays quiet through",
           load("nudgy", tmp)["tick"] >= 2)
        ck("a standing signal repeats after the interval",
           bool(safe_nudge("nudgy", tmp, bump=NUDGE_EVERY_TICKS)))
        g2 = load("nudgy", tmp)
        add(g2, "off the net entirely", kind="goal")
        save(g2, tmp)
        ck("a new signal fires at once, without waiting for the interval",
           bool(safe_nudge("nudgy", tmp)))
        ck("safe_status describes a live graph", "goal-net" in safe_status("nudgy", tmp))

        # a directory where the file should be: unreadable, and still must not raise
        (tmp / "dirfile.json").mkdir()
        ck("a directory in the way reads as empty", load("dirfile", tmp)["nodes"] == {})
        ck("and safe_nudge stays quiet", safe_nudge("dirfile", tmp) == "")

        # ---------- scale: the traversals stay linear enough to run in a hook ----------
        g = empty_graph("big")
        c = add(g, "core", kind="core")
        prev = c
        chain = []
        for i in range(400):
            prev = add(g, f"deep {i}", [prev])
            chain.append(prev)
        t0 = time.time()
        ck("a 400-deep walk back reaches core", path_to_core(g, prev)[-1] == c)
        ck("a deep net check holds", net(g)["ok"])
        ck("and it is fast enough for a hook", time.time() - t0 < 3.0)
        ck("tree renders a deep graph", render_tree(g).count("\n") >= 400)
        raises("the node cap is enforced",
               lambda: [add(g, f"x{i}") for i in range(MAX_NODES + 1)])

        # ---------- the ledger ----------
        led = tmp / "led.jsonl"
        ledger({"event": "test", "session": "s"}, led)
        ledger({"event": "test2", "session": "s"}, led)
        lines = led.read_text(encoding="utf-8").strip().split("\n")
        ck("the ledger appends", len(lines) == 2)
        ck("every line is json and stamped",
           all(json.loads(x).get("at") for x in lines))
        ledger({"event": "x"}, tmp / "no" / "such" / "dir" / "led.jsonl")
        ck("an unwritable ledger does not raise", True)

        # ---------- the CLI, end to end, in a real directory ----------
        global STATE_DIR, LEDGER
        old_dir, old_led = STATE_DIR, LEDGER
        STATE_DIR, LEDGER = tmp / "cli", tmp / "cli.jsonl"
        # The CLI prints for a person. Here the verdict line is the only output that
        # matters, and burying it under sixty lines of demo is how a green run gets read
        # as a failure.
        import contextlib
        import io
        try:
          with contextlib.redirect_stdout(io.StringIO()), \
               contextlib.redirect_stderr(io.StringIO()):
            ck("cli status on nothing exits 0", main(["--session", "cli"]) == 0)
            ck("cli net on nothing exits 0", main(["--session", "cli", "--net"]) == 0)
            ck("cli drift on nothing exits 1", main(["--session", "cli", "--drift"]) == 1)
            ck("cli add refuses a bad parent",
               main(["--session", "cli", "--add", "x", "--parent", "ghost"]) == 2)
            ck("cli add works",
               main(["--session", "cli", "--add", "core", "--kind", "core",
                     "--id", "c1"]) == 0)
            ck("cli add a child works",
               main(["--session", "cli", "--add", "job", "--parent", "c1",
                     "--id", "j1", "--kind", "goal"]) == 0)
            ck("cli activate works",
               main(["--session", "cli", "--activate", "j1"]) == 0)
            ck("cli add a second goal",
               main(["--session", "cli", "--add", "fire", "--parent", "c1",
                     "--id", "f1", "--kind", "goal"]) == 0)
            ck("cli switch works",
               main(["--session", "cli", "--activate", "f1", "--reason", "LAW 1",
                     "--cp-next", "read the log"]) == 0)
            gg = load("cli", tmp / "cli")
            ck("cli parked the old job", [f["node"] for f in gg["stack"]] == ["j1"])
            ck("cli kept the checkpoint",
               gg["stack"][0]["checkpoint"]["next"] == "read the log")
            ck("cli close works", main(["--session", "cli", "--close", "f1"]) == 0)
            ck("cli resume works", main(["--session", "cli", "--resume"]) == 0)
            ck("cli resume with nothing parked exits 1",
               main(["--session", "cli", "--resume"]) == 1)
            ck("cli net holds", main(["--session", "cli", "--net"]) == 0)
            ck("cli net --json holds", main(["--session", "cli", "--net", "--json"]) == 0)
            ck("cli path works", main(["--session", "cli", "--path"]) == 0)
            ck("cli tree works", main(["--session", "cli", "--tree"]) == 0)
            ck("cli tick works", main(["--session", "cli", "--tick", "5"]) == 0)
            ck("cli reset works", main(["--session", "cli", "--reset"]) == 0)
            ck("cli reset twice is fine", main(["--session", "cli", "--reset"]) == 0)

            # Prefix ids. The generated ids carry the text, so nobody types them whole.
            main(["--session", "px", "--add", "retire fly io", "--kind", "core"])
            main(["--session", "px", "--add", "move dns", "--parent", "n1"])
            gp = load("px", tmp / "cli")
            ck("a bare counter resolves to the slug id",
               sorted(gp["nodes"]) == ["n1-retire-fly-io", "n2-move-dns"]
               and gp["nodes"]["n2-move-dns"]["parents"] == ["n1-retire-fly-io"])
            ck("a prefix activates", main(["--session", "px", "--activate", "n2"]) == 0)
            ck("a prefix closes", main(["--session", "px", "--close", "n2"]) == 0)
            main(["--session", "px", "--add", "n-thing", "--parent", "n1", "--id", "n22a"])
            main(["--session", "px", "--add", "other", "--parent", "n1", "--id", "n22b"])
            ck("AN AMBIGUOUS PREFIX REFUSES rather than guessing which objective was meant",
               main(["--session", "px", "--activate", "n22"]) == 2)
            ck("and the full id still works when it is a prefix of another",
               main(["--session", "px", "--activate", "n22a"]) == 0)
            ck("an unknown id is still an unknown id, not a silent no-op",
               main(["--session", "px", "--activate", "nope"]) == 2)
        finally:
            STATE_DIR, LEDGER = old_dir, old_led
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        print(f"goal_graph selftest: {len(fails)} of {checks['n']} checks FAILED")
        for f in fails:
            print(f"  FAIL  {f}")
        return 1
    print(f"goal_graph selftest: {checks['n']} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
