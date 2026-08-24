# Drill coverage — what it is and how to stop it

## What is this for

You asked whether the Kimi bridge and Aiden were under drill, and nothing on the estate could answer
it. The drills were passing and the asset list had 194 rows in it, but the two were never joined, so
an asset nobody had ever thought about losing looked exactly like one that was covered.

This joins them. It reads the asset list, applies a small set of rules, and says for every asset
either which drill brings it back or why it does not need one. There is no third answer. An asset
that fits neither is reported by name.

The reason it asks three questions rather than one is that "is it drilled" has three answers and
they disagree:

- **restart** — it stops, and it comes back, on this machine.
- **rebuild** — this laptop dies and it comes back on a new one.
- **replace** — the company behind it is gone and the estate still works.

Aiden passes the first and third and fails the second. Asked as one question it read as covered,
which is how it stayed hidden.

Which of the three apply is a property of the kind of thing. A ledger does not restart. A repository
does not restart. A drill is not itself an asset to be drilled.

## What it costs

A few seconds of CPU once a night, inside a job that already runs. It reads two files that already
exist and writes nothing. No network, no money.

## What it watches or changes

It watches, and changes nothing. It reads the asset list at `~/.estate/state/inventory.json`, which
a different job refreshes daily, and the rules at `drills/coverage.json`. Every night `drills/run.py
--all` runs it and posts one line to the estate board; the founder board renders the same number as
a row called "assets with a way back".

Two failures live in that report and they are not the same thing.

A **hole** is an asset nobody has classified. There were 111 on 2026-08-24, and that is a fact about
the estate rather than a bug. It is reported, it is on the board, and it is the number that has to
fall. It does not turn anything red, because a board that is red every night for a month is a board
people stop reading.

A **broken answer key** is a defect in this tool: a rule keyed on something no asset actually has, a
drill name that is not on the register, a kind it has never been taught, an asset list too old to
believe. That makes every other number in the report a lie, so it is red and it is fixed in minutes.
`--gate` is the flag that separates the two: it exits 1 only on the second.

## Where it lives

```
drills/coverage.py        the tool
drills/coverage.json      the rules, and the reasons for every dismissal
drills/test_coverage.py   the control: 13 cases, 5 that must be allowed and 8 refused
drills/register.json      the drills the rules are allowed to point at
```

Nothing here is generated. `coverage.json` is written by hand on purpose, because the interesting
part of it is the sentence saying why an asset does not need a drill, and no tool can write that.

## How to turn it off

```
touch ~/.claude/state/coverage-off
```

That stops the nightly line and takes the row off the board, together, because a switch that
silences half a thing is one nobody trusts. Nothing else changes: the drills still run, the asset
list still refreshes, and the tool still answers anyone who asks it directly. Turning off a report
is not the same as turning off an instrument.

## How to turn it back on

```
rm ~/.claude/state/coverage-off
```

## What goes wrong

**The asset list goes stale.** If the job that refreshes it dies, this refuses rather than reporting
green on old data — an old list is confident about assets that are gone and silent about ones that
arrived. The bar is 48 hours. The fix is the inventory job, not this.

**A rule stops matching anything.** This is the failure that already happened: a rule about losing
GitHub was keyed on remotes starting `github.com/` when every remote recorded starts
`https://github.com/`, so it matched zero of 20 repositories and nothing complained. The check that
catches it now needs at least three assets of a kind before it will call a rule dead, because on a
tiny estate "nothing matched" is not evidence of anything.

**A drill is on paper only.** A rule can point at a drill that is registered but not yet written.
Those are listed separately, with a count of how much rests on them. `github-gone` currently carries
22 asset slots and does not exist yet, which makes it the most valuable unwritten drill on the
estate.
