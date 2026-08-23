# law-writer — demo

The estate writes its own laws from what actually happened, ranked by what each pattern
costs rather than by how often it fired.

## What a session sees

```
$ python3 ~/.claude/scripts/law-writer.py --hook
```

```
[laws/dynamic] WRITTEN FROM WHAT ACTUALLY HAPPENED, NOT FROM OPINION.
Each line was counted on this estate in the last 7 days. The static laws in
~/AGENTS.md outrank every line here. Refreshed 4m ago.

  D1 (cost 84) Start the long job first and say what you are waiting on, then stop.
  D2 (cost 70) Do not trust telegram_ledger.py until it is fixed; it reported itself broken.
  D3 (cost 68) Prove the thing runs before reporting it done. Installed is not operational.
  D4 (cost 60) Do not trust tool-drip-guard.py until it is fixed; it reported itself broken.
  D5 (cost 60) Do not trust estate_alert.py until it is fixed; it reported itself broken.
  D6 (cost 42) Do not trust guard_report.py until it is fixed; it reported itself broken.

  Contradictions in the rulebook itself -- do not cite a law by number until fixed:
    - LAWS-INCIDENTS.md is indexed against a different law numbering. 3 of 32 law numbers point at the wrong incident
```

A founder complaint counts at one and outranks a flood of cheap guard refusals, because a
guard refusal is a thing a machine already stopped and a complaint is a thing that already
cost trust.

## Checking the laws for ambiguity

```
$ python3 ~/.claude/scripts/law-writer.py --audit
```

```
# Law ambiguity audit

A law that commands analysis but does not say WHAT to sweep is obeyed differently by
every agent, because each one picks its own dimensions. The dimensions are the founder's:
surfaces, dependencies, edge cases, unknowns, unknown unknowns, risk.

## Commands analysis, does not say what to sweep (0 of 32 laws)

```

```
$ python3 ~/.claude/scripts/law-writer.py --selftest
  ok   static subjects are readable
law-writer selftest: 13/13 checks passed
```
