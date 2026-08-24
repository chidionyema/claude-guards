# Drill coverage — what it looks like when it runs

The question that produced this was one sentence: are the Kimi bridge and Aiden under drill?
Nothing on the estate could answer it. The drills were green, the asset list had 194 rows, and
nothing joined the two, so every asset read the same whether somebody had thought about losing it
or not.

This is the join. It asks three separate questions of every asset instead of one, because "is it
drilled" has three answers and they disagree.

## The question that started it

```
$ python3 drills/coverage.py --asset aiden
ai.aiden.watch   [scheduled_job]  coupling=anthropic
  restart   drill: recovery-posture         [every launchd job is graded for restart]
  rebuild   UNCLASSIFIED   nobody has said what happens when this is lost
  replace   drill: no-anthropic             [a job with a vendor behind it rides on the vendor drill]

.claude/state/aiden-ticks.jsonl   [ledger]  coupling=anthropic
  rebuild   drill: offsite-backup-restore   [a ledger the backup collects has a way back]
```

Aiden restarts on this machine and survives Anthropic leaving. It does not come back on a new
machine: it is one of the 12 jobs `jobs/jobs.json` cannot re-render, so a rebuild stands the estate
up without it. Asked as one question it read as covered, because `recovery-posture` passes and
grades every launchd job on this Mac.

The Kimi bridge is in `jobs.json`, so it answers differently on the middle line:

```
$ python3 drills/coverage.py --asset kimi
ai.estate.kimi-bridge   [scheduled_job]  coupling=anthropic
  restart   drill: recovery-posture         [every launchd job is graded for restart]
  rebuild   drill: rebuild                  [a job jobs.json can re-render survives this laptop]
  replace   drill: no-anthropic             [a job with a vendor behind it rides on the vendor drill]
```

## The whole estate

```
$ python3 drills/coverage.py
203 assets in 6 kinds, asset list generated 2026-08-24T02:34:01Z

  kind            assets  slots                    covered  dismissed  UNCLASSIFIED
  data                11  rebuild                        1          0            10
  drill               13  -- not an asset to drill
  guard               32  rebuild/replace               32         11            21
  ledger              77  rebuild                       15          0            62
  repo                24  rebuild/replace               45          0             3
  scheduled_job       46  restart/rebuild/replace       98         25            15

covered on paper only, because these drills are NOT WRITTEN:
  github-gone              22 asset slot(s) rest on it

111 asset slot(s) nobody has classified. Each is an asset whose loss has never been thought about:
  data            transcripts                                  rebuild
  data            telemetry                                    rebuild
  data            toolguard-decisions                          rebuild
  guard           agent-fleet-fence.py                         replace
  guard           canonical-root-guard.py                      replace
  ...

SUMMARY: 111 unclassified of 338 asset slot(s) across 203 assets
```

227 of 338 have an answer. 111 do not, and that is the number this exists to move. The three big
groups behind it are named in `coverage.json` so nobody mistakes them for an oversight: 62 ledgers
and 10 data trees no offsite copy carries, 21 guards that only fire inside Claude Code, and the 15
jobs a rebuild cannot re-render.

The numbers move between runs, and that is the point rather than a wobble: this run is nine assets
larger than the one two hours before it, because the estate grew and the asset list caught it. A
report that read the same every night would be reading a document, not the estate.

## The control

A gate is finished when it has been shown to allow correct work, not when it refuses the bad case.

```
$ python3 drills/test_coverage.py
  pass  [yes ] allows a fully classified estate
  pass  [yes ] allows an estate of only drills, which are not assets to drill
  pass  [yes ] allows an empty estate rather than inventing a problem
  pass  [NO  ] refuses an asset nobody classified
  pass  [NO  ] refuses a stale asset list instead of reporting green on it
  pass  [NO  ] refuses a missing asset list, because unknown is not zero
  pass  [NO  ] refuses an asset list with no generation stamp
  pass  [NO  ] refuses a kind it has never been taught about
  pass  [NO  ] refuses a rule that matches nothing, the GitHub prefix bug
  pass  [yes ] allows a rule pair where only one half matches this estate
  pass  [yes ] --gate lets an estate with holes in it through, because that number is reported and not gated
  pass  [NO  ] --gate still refuses a broken answer key
  pass  [NO  ] refuses a drill name that is not on the register

13/13 passed: 5 that must be ALLOWED, 8 that must be REFUSED
```

Those cases earned their place. The control caught three real defects in this code, all of the same
shape: refusing work that was correct. The dead-rule check reported both halves of a working rule
pair as broken; then it reported a one-row estate as broken; and the GitHub rule it was written to
catch had itself matched zero of 20 repositories because it was keyed on `github.com/` when every
remote recorded starts `https://github.com/`.
