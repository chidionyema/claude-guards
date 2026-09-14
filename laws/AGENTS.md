# THE HEADLINE — ABOVE ALL LAWS

One platform, one name: `~/dev/code/idp`. Shared layers (routing, audit, identity, secrets,
scheduling, catalog, CI) exist once, in idp.

Never: (1) script what a proven platform already solves; (2) hand the founder a menu — name one
answer, state the risk, do it; (3) ship anything a buyer's engineer could take apart in one
sitting.

# HYPER EFFICIENCY — ranks with correctness

Token cost is a primary constraint. Fewest probes. Delete paperwork gates, don't feed them. Batch
every similar fix in one pass. No narration.

# Reply format (dod-guard enforces this)

Line 1: `DONE:` / `INVENTORY:` / `BLOCKED:` / `WORKING:` / `WAITING:` / `STAGED:` + one plain
sentence. `INVENTORY:` needs all five: `Built:` `Use:` `Expect:` `Not done:` `Evidence:`. `DONE:`
also needs `Founder receipt:`. Plain English, no jargon.

# Execution boundary

60s ceiling, outside your process. Run via `bin/idp-exec`; longer work → `dispatch_job`, never
`timeout`/`&`.

# Everything else lives in one file, read on demand — not injected here

All 55 laws in full, the Empirical Proof Rule, the Four Hard Rules, the Medic law, SSO, the Flake
protocol, Compact-instructions spec: `~/AGENTS-FULL.md`. Incidents: `~/.claude/LAWS-INCIDENTS.md`.
