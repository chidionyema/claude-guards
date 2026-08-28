# Archived guards

A guard whose rule now lives in `policy/*.rego` (crew#603 CP5) is moved here, never deleted:
the history stays readable, and `hooks.rego` (`revive_verbs`) refuses any command or settings edit that
would run a file under this directory (archive-not-delete, unrevivable). Each file's rule and tests
are in Rego; the Python is the record of what was ported.

| Archived | Rule now in | Since |
|---|---|---|
| `scope-guard.py` | `policy/hooks.rego` (`scope_*`, two `deny` rules) | 2026-08-28 |
| `canonical-root-guard.py` | `policy/session.rego` (`cwd_verdict`, one `context` rule) | 2026-08-28 |
| `jargon-guard.py` | `policy/reply.rego` (`jargon`, `jargon_hits`, one `deny`) | 2026-08-29 |
| `dod-guard.py` | `policy/reply.rego` (`dod_offences`, one `deny`) | 2026-08-29 |
| `blocker-guard.py` | `policy/reply.rego` (`blocker_row`, two `deny`); the door supplies `telegram_ledger` | 2026-08-29 |
