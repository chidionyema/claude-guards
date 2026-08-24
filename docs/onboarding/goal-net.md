# Goal net: onboarding

You do not have to run anything to benefit from this. If you never touch
`goal_graph.py`, nothing changes: the guard stays silent about a net you do not
have. This page is for the session that wants the walk-back to actually point
somewhere.

## What it is for

A session loses its objective before it loses anything else. Compaction takes it
first, and a context switch takes it quietly. The old drift guard held one sentence
on disk and reminded you of it; measured on 2026-08-24, session `8ef72725` had
fired that reminder 34 times with the sentence empty.

This holds the objective as a net instead. Nodes are objectives and tasks, edges
point at parents, and an edge means "this exists in order to serve that". So the
tool can answer two questions a sentence cannot: what does the thing I am doing
right now serve, and what did I abandon to start it.

## Three commands is the whole of it

```
goal_graph.py --add "the objective" --kind core     # once, at the top
goal_graph.py --add "a piece of it" --parent n1     # decomposition
goal_graph.py --activate n2                         # where you are now
```

Ids are printed when you add a node. Any prefix that means one node works, so
`--activate n2` finds `n2-move-mumchimp-dns-off-fl`.

## When you switch away from something

This is the part that pays for itself. Say why, and say what the next step would
have been:

```
goal_graph.py --activate n5 --reason "P1 fire" --cp-next "re-run the migration"
```

The old node is parked with that checkpoint. When you close the thing you switched
to, the parked work is handed straight back, and `--resume` puts you on it with the
checkpoint reprinted. Pre-switch work outranks anything newer, which is the whole
rule.

## What it does on its own

`goal-guard.py` already runs on `SessionStart` and `PreToolUse`. It now reads the
net at both:

- On session start and after a compaction it re-injects the path you were on and
  anything parked. Work parked before a compaction is work nothing else on this
  machine remembers.
- On tool calls it advances a tick and, when a drift signal fires, appends the walk
  back to core and the parked list to the message it was already sending.

It advises. It never refuses a tool call, and it rate limits itself: a new signal
fires once, and a signal you have already been told about repeats at most every 20
ticks. A guard that talks over correct work is an outage, not a feature.

## The signals

Eight, and all of them structural. None reads your transcript and none calls a
model, because an estate running six sessions cannot pay for an embedding per tool
call, and reachability is exact where a similarity threshold is a number somebody
has to tune.

`no_graph`, `no_active`, `off_net` (working on something that reaches no core
objective), `parked_abandoned`, `stack_deep`, `thrash` (switching too often),
`stall`, `net_broken`.

Deeper is not a switch and shallower is not a switch. Decomposing a task is the job
and coming back up is finishing a piece; only a sideways move counts. That
distinction is why the thrash signal can be believed.

## Checking it

```
goal_graph.py --status     # where you are, one screen
goal_graph.py --tree       # the whole net
goal_graph.py --net        # nine invariants, exit 1 if broken
goal_graph.py --drift      # eight signals, exit 1 if drifting
```

Both `--net` and `--drift` exit non-zero when they find something, so a cron job or
a CI step can read them without parsing text.

## Thresholds

The starting numbers are guesses and are labelled as such in the module: parked
work goes stale at 30 minutes or 60 ticks, a stall is 80 ticks, thrash is 3
switches inside 20 ticks. They are meant to be measured from
`~/.claude/state/goal-net.jsonl` and corrected, the way `goal-guard.py`'s own
read-only limit started at 25 and was measured down to 16.

## If it breaks

It cannot take a session with it. Every path into the store fails open: a truncated
file, a hand-edited file of the wrong shape, a directory where the file should be,
and a session id containing `../` all resolve to an empty graph instead of an
exception. The guard's import of it is inside a try, and there is a check that
proves a `goal_graph` which cannot be imported at all still lets the tool call
through.
