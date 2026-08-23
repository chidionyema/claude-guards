# Demo — a budget per ticket, and what the work actually cost

Two numbers that never used to exist in the same place: what a piece of work was expected to cost,
and what it took. The second one is the hard half, and it is the reason this is worth building.
Every turn of every session writes its own token usage into its transcript, and every session is
already bound to a GitHub issue, so the actual cost of an issue is a sum nobody had bothered to add
up.

## The estate, priced

```
$ python3 /tmp/cost.py
sessions with usage: 78103
TOTAL recorded spend: $84,078
median session: $0.00

most expensive sessions:
  $ 3,687.85 11012 turns  74f4ed5c  -Users-chidionyema-Docum
  $ 3,497.32 10212 turns  3fa47c70  -Users-chidionyema-Docum
  $ 2,383.23  7847 turns  5a5eafd3  -Users-chidionyema-Libra
  $ 2,093.51  6727 turns  1154e812  -Users-chidionyema-Docum
  $ 1,770.95  5523 turns  56afe97f  -Users-chidionyema-Docum
  $ 1,628.48  4611 turns  539d1063  -private-tmp-claude-501-

where the money goes:
  input_tokens                           5,981,108  $       90    0.1%
  output_tokens                        287,495,896  $   21,562   25.6%
  cache_creation_input_tokens        1,477,752,900  $   27,708   33.0%
  cache_read_input_tokens           23,145,450,620  $   34,718   41.3%
```

That is token value at Opus 5 list prices, not money that left the account. It is the right number
for comparing one piece of work against another, which is what a budget is for.

The line that matters is the last one. Fresh thinking — the input tokens of an actual question —
is 0.1% of the total. Three quarters of everything is cache: context carried forward, re-billed
every turn. A session that wanders costs the same per turn as one that does not, and it takes more
turns.

## One issue, budget against actual

```
$ python3 -c '... g.budget_line(46, body)'
this session: $281.94 over 766 turns, measured in 0.8s
budget_line(46): spent $281.94 over 766 turns in 1 session(s)  budget $12.00 (+$269.94)
actuals(46): {'cost': 281.939511, 'turns': 766, 'sessions': 1}
```

The $12 there is a budget written by hand to prove the comparison. The $281.94 is real: it is this
session, summed from its own transcript, and it took 0.8 seconds to work out.

## The sweep, reporting how many tickets have no budget at all

```
$ python3 ticket-gate.py --close-sweep
{
  "checked": 1,
  "closed": [],
  "failed": [45],
  "no_criteria": 24,
  "no_budget": 25,
  "budget_hit": false
}
```

Twenty-five open issues, none of them budgeted. That count is the starting point, and it is the
number that should fall.

## The parser, proved without a network

```
$ python3 ticket-gate.py --selftest-close
  ok   no Budget block reads as unset
  ok   cost and time are read
  ok   hours become minutes
  ok   a budget block ends at the next heading
  ok   prose in the block is skipped, not guessed at
  ...
selftest-close: 21/21 passed
```

The first of those is the control that matters. An issue with no budget has to read as no budget
and not as a budget of zero, because zero is a number the comparison would happily print as "over
by $281" on every close.
