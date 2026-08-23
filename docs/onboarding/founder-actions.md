# Onboarding: what is waiting on the founder

## What this is for

Some steps genuinely cannot be done by an agent. Proving your identity to a platform, moving
money, an irreversible act, or clearing a guard that is doing its job correctly. LAW 31 says you
do not run commands, so every one of those steps is friction we owe you an answer for.

Until this existed, that friction was retail. An agent hit a wall only you could clear, spent a
reply telling you about that one wall, and the next agent did the same for a different one.
Measured in one session on 2026-08-23: three separate items surfaced in three separate turns, none
of them visible anywhere afterwards, and none of them visible next to the others. You could never
clear more in one visit than whatever you happened to be reading about at the time.

This collects them. One list, on the board you already have open, each with the reason it is
yours and what it releases when you clear it.

## What it costs

Nothing recurring. It is one Python file with no dependencies outside the standard library, and
it runs inside the hourly estate audit that already runs. The register is a plain JSONL file, so
there is no database and nothing to back up beyond the file itself.

## What it watches, and what it changes

It watches a register at `~/.claude/state/founder-actions.jsonl`. Agents append to it when they
hit an authorisation wall. It changes nothing else on the machine, ever. It has no network
access, it writes no secrets, and the only file it modifies is the register.

An item closes when a shell command says the world changed, not when an agent says so. If the
command exits 0 the item is done and the next sweep drops it. An item that no command can settle
is allowed and reads `CANNOT TELL`, never `CLEAN`, because the honest answer to "did he put the
key in a password manager" is that this machine cannot see inside one.

## Where it lives

- The register: `~/.claude/state/founder-actions.jsonl`
- The code: `~/.claude/scripts/founder_actions.py`
- The rows on your board: `c_founder_actions()` in `~/.claude/scripts/estate/estate_audit.py`
- Your board: http://127.0.0.1:8787, under access and change control

## How to turn it off

One command, and it takes the rows off your board immediately:

```
python3 - <<'EOF'
import pathlib, re
f = pathlib.Path.home() / ".claude/scripts/estate/estate_audit.py"
f.write_text(f.read_text().replace("CHECKS.append(c_founder_actions)",
                                   "# CHECKS.append(c_founder_actions)  # off"))
EOF
```

Nothing else on the machine depends on it, so that is the whole of the off switch. The register
file stays where it is and is harmless.

## How to turn it back on

Reverse the same line, changing `# CHECKS.append(c_founder_actions)  # off` back to
`CHECKS.append(c_founder_actions)`. The register was never deleted, so every item comes back with
its history intact.

## What goes wrong

**A `done_when` that hangs.** It is killed after 20 seconds and the item reads open, never done.
A slow check can never produce a false clear.

**A malformed line in the register.** It is surfaced as an item called `__malformed_line_N` rather
than skipped, because a register that silently drops a line is worse than one that is noisy.

**An agent writing an item that is not really yours.** That is the failure mode worth watching. If
something appears on this list that an agent could have done itself, it is a bug in that agent's
judgement, not in this list, and LAW 5 is the rule it broke.
