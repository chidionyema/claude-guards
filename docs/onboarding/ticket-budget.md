# A budget per ticket

## What it is for

To catch drift while it is still cheap. An agent four hops off the job it was given spends money at
the same rate as one on it, and until now nothing on this machine could tell the two apart. A budget
written on the ticket before the work starts, compared against what the work actually took, is the
signal that shows up before you notice something is wrong.

It is not an accounting exercise. The estimate on its own is worth very little. The comparison is
the whole point, which is why this was only worth building once the actual became measurable.

## What it costs

Nothing to run. The budget is a few lines of text in an issue body. Working out what an issue
actually cost takes under a second: it reads the transcripts of the sessions bound to that issue and
sums the usage numbers each turn already writes. It happens once, when the issue closes.

## What it watches

Open issues in `chidionyema/crew`. Every half hour a sweep reads them, runs each issue's acceptance
criteria, and closes the ones that pass. When it closes one it adds a line saying what that issue
cost and how that compares with its budget. It also counts how many open issues have no budget at
all — 25 out of 25, when this was written.

It changes nothing except closing issues that have proved themselves. It never opens, edits or
reopens anything.

## How to write a budget

Put this block anywhere in the issue body:

```
## Budget
- cost: $25
- time: 90m
```

Both lines are optional. Hours work too (`- time: 2h`). Anything that is not a number is ignored
rather than guessed at, so `- cost: roughly a tenner` reads as no budget rather than as zero.

## Where it lives

`~/.claude/scripts/ticket-gate.py`, in the crew scripts repository. It runs from the aiden tick,
which launchd fires every five minutes.

## How to turn it off

```
launchctl unload ~/Library/LaunchAgents/com.founder.aiden.plist
```

That stops the whole tick, including the closing of tickets and the phone alerts. To stop only the
budget line and keep everything else, delete the `## Budget` blocks from the issues; with no budget
written, nothing is compared and nothing is printed.

## How to turn it back on

```
launchctl load ~/Library/LaunchAgents/com.founder.aiden.plist
```

## What goes wrong

The failure already seen, on the first unattended run: `gh` was not on the scheduler's PATH, so the
sweep raised `FileNotFoundError` and closed nothing while the same code worked by hand in a
terminal. It now resolves the absolute path. The general shape of that failure is worth knowing —
anything that works when an agent tests it and fails under launchd is almost always PATH.

The second thing to expect is that the numbers are token value at list prices, not a bill. They are
comparable to each other, which is what a budget needs, but they are not what the account was
charged.
