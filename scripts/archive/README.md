# Archived guards

A guard whose rule now lives in `policy/*.rego` (crew#603 CP5) is moved here, never deleted:
the history stays readable, and `hooks.rego` (`revive_verbs`) refuses any command or settings edit that
would run a file under this directory (archive-not-delete, unrevivable). Each file's rule and tests
are in Rego; the Python is the record of what was ported.

| Archived | Rule now in | Since |
|---|---|---|
| `scope-guard.py` | `policy/hooks.rego` (`scope_*`, two `deny` rules) | 2026-08-28 |
