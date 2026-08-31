# The verification layer, onboarding

## What it is for

On 2026-08-29 two sessions told the founder a service was reachable when their own probe had
stopped at a sign-in page. The founder's spec (`~/.claude/docs/founder/2026-08-29T2213Z-crew-628-verification-layer-4e0f20e1.md`,
crew#656) replaces trust in what a session says with a check at the moment of writing, a record
of what it did, and a ledger that gates who may touch production.

## The pieces, and where each lives

| piece | file | hook or caller |
|---|---|---|
| vocabulary (phase 0) | `state_vocabulary.py` | `estate-broadcast.py` before every board post |
| claim envelope and gate (phase 2) | `claim_gate.py` | `estate-broadcast.py`, `feed-guard.py append`, `dod-guard.py` (Stop hook, founder replies) |
| tool-call record (phase 5) | `tool-call-recorder.py` | `PostToolUse` (every tool), `UserPromptSubmit` (turn counter), `SessionStart` (canary notice) |
| canary auditor (phase 4 and 5) | `canary-auditor.py` | run by the estate clock after `pull`; the canary workload and injection log are in `idp/platform/staging/canary` |
| ledger and promotion gate (phase 6) | `verification-ledger.py` | `build` by the estate clock; `hook` on `PreToolUse` Bash, fires only on a `git push` that changes platform/ or clusters/ |

Settings: `settings/settings.json` here and `~/.claude/settings.json` in claude-estate carry the
same four hook lines.

## The three states

`MEASURED_OK`, `MEASURED_FAIL`, `UNKNOWN`. Nothing else. `up`, `down`, `healthy`, `working`,
`fine`, `operational` and `broken` are refused by name when used about a service. A peer's word
is a `LEAD`, carries `UNKNOWN`, and names its source.

## The envelope

```claim
{"claim": "what is asserted", "state": "MEASURED_OK", "service": "backstage",
 "evidence": {"kind": "command", "command": "bin/idp-prove backstage", "exit_code": 0,
              "output": "...", "observed_at": "2026-08-31T06:00:00Z"}}
```

`kind` is `metric` (a `query` the gate runs against the metric store), `command` (an exit code
and up to 512 bytes of output) or `none` (only with UNKNOWN). The rejection table is in
`claim_gate.validate`; the founder's spec section 4.2 is its source, row for row.

## Configuration, all with defaults

| setting | where | default |
|---|---|---|
| freshness window | `CLAIM_GATE_FRESHNESS_SECONDS`, or `freshnessSeconds:` in `$ESTATE_PROBES_DIR/<service>.yaml` | 180 |
| metric store | `ESTATE_PROMETHEUS_URL` | none; a metric claim then reads GATE_UNAVAILABLE |
| claims log | `CLAIM_GATE_LOG` | `~/.estate/claims.jsonl` |
| tool records | `TOOL_CALL_RECORD_DIR` | `~/.estate/tool-calls/` |
| canary namespace | `CANARY_NAMESPACE` | `staging` |
| ledger window | `VERIFICATION_LEDGER_DAYS` | 7 |
| thresholds | `~/.estate/verification-thresholds.yaml` (`min_claims`, `min_verification_rate`, `min_canary_windows`, `max_canary_misses`, `max_retractions`, `enforce`) | absent: nothing qualifies, the gate reports only |

## What fails how

Content fails closed: a claim without evidence is not written anywhere. Configuration fails
loud: a gate that cannot load, or a metric store that cannot be reached, prints
`GATE_UNAVAILABLE` and the board still carries the post, because the board is the channel
the estate reports a broken gate on. Override for a quotation that has to carry banned words:
`ESTATE_VOCABULARY_OVERRIDE=1`.

## The spec, executable

`features/verification_{vocabulary,claim_envelope,tool_call_audit,ledger}.feature`, bound by
`tests/test_verification_*_feature.py`. The prober, prober fleet and canary features are bound in
`idp`. The wording is the founder's spec; a scenario that cannot pass is a defect here, not
in the feature file.
