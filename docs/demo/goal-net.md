# The goal net, demonstrated

Every block below is a real run of `goal_graph.py`, pasted from the terminal on
2026-08-24. Nothing here is illustrative.

The problem it was built for is measurable. On session `8ef72725` the same day,
`goal-guard.py` had fired its drift walk-back 34 times across 1,183 tool calls, and
the state file held `"goal": ""`. Thirty-four reminders pointed at nothing, because
one sentence on disk is all the old guard could hold, and there was no sentence.

## Objectives are a net, not a list

A node records what it is for. An edge points at a parent, so an edge means "this
exists in order to serve that". Parents are a list, not one field, so a task can
serve two objectives at once. That is the difference between a tree and a net.

```
$ goal_graph.py --add "retire fly io" --kind core
n1-retire-fly-io

$ goal_graph.py --add "move mumchimp dns off fly" --parent n1
n2-move-mumchimp-dns-off-fl
```

Ids carry the text, because an id has to be readable inside a nudge. Nobody types
them whole: any prefix that can only mean one node works, and an ambiguous prefix
refuses and names the candidates rather than guessing.

## Walking back to core

```
$ goal_graph.py --activate n2
same: [task] move mumchimp dns off fly  (n2-move-mumchimp-dns-off-fl, active)
[task] move mumchimp dns off fly  (n2-move-mumchimp-dns-off-fl, active)
  ^ serves [CORE] retire fly io  (n1-retire-fly-io, open)
```

That is the founder's ask "you can work your way back to core goals" as a command.
The walk is exact, not a similarity score: either an edge exists or it does not.

## A context switch is parked, with a checkpoint

Moving to a node that is neither an ancestor nor a descendant is a context switch.
Moving deeper is decomposition, which is the job, and moving back up is finishing a
piece; neither of those is a switch, which is why the guard can be believed when it
says one happened.

```
$ goal_graph.py --activate n3 --reason "dns needs a founder decision" --cp-next "ask which A record wins"
sideways: [task] price a linux box for ship_shop  (n3-price-a-linux-box-for-sh, active)
parked, and waiting: [task] move mumchimp dns off fly  (n2-move-mumchimp-dns-off-fl, parked)
```

## Finishing the new thing hands back the old one

```
$ goal_graph.py --close n3 --note "quoted, 6 GBP a month"
next: [task] move mumchimp dns off fly  (n2-move-mumchimp-dns-off-fl, parked)  (parked before a context switch)

$ goal_graph.py --resume
back on: [task] move mumchimp dns off fly  (n2-move-mumchimp-dns-off-fl, active)
  next: ask which A record wins
```

Pre-switch work outranks anything newer. The checkpoint written at the switch comes
back with it, so the return is a resume and not a restart.

## Drift, when the return never happens

```
$ goal_graph.py --tick 70
70

$ goal_graph.py --drift
[goal-net] work parked at a context switch and never returned to.

Where you are, and what it serves:
[task] chase prospector PR 687  (n4-chase-prospector-pr-687, active)
  ^ serves [CORE] retire fly io  (n1-retire-fly-io, open)

Parked at a context switch, oldest last. Finish or drop these:
  [task] move mumchimp dns off fly  (n2-move-mumchimp-dns-off-fl, parked)
      left because: PR looked closer to green
      next: register vendor_ratchet in console_api TOOLS

  Return with: goal_graph.py --resume    (goes back to n2-move-mumchimp-dns-off-fl)
exit 1
```

Drift is counted in tool calls, never in seconds. A session waiting twenty minutes
on a CI run is not drifting, and a wall clock cannot tell those two apart.

## The whole net, checked

`--net` runs nine invariants: malformed nodes, dangling parents, cycles, work that
reaches no core objective, an active node that disagrees with the graph, a broken
resume stack, a parked node that is not on it, a closed node with open children,
and a stray root. `--drift` runs eight signals. Both exit 1 when they find
something, so cron and CI can read them.

## Proof

```
$ python3 goal_graph.py --selftest | tail -1
goal_graph selftest: 174 checks passed

$ python3 goal-guard.py --selftest | tail -1
  76/76 checks passed
```

174 checks cover the empty world, everything `add` refuses, a two-parent diamond,
every value of `relation`, double-parking, resuming past a node closed while it was
parked, hand-edited stores, hostile session ids, a directory where the file should
be, a 400-deep chain against a 3-second budget, and the CLI end to end. The 76 in
goal-guard include the wiring, and both halves of it: a healthy net produces no
nudge at all, and a `goal_graph` that cannot even be imported still lets the tool
call through.
