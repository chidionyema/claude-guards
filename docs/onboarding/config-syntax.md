# Config syntax — what it is and how to stop it

## What is this for

A service reads a config file when it starts. If the file will not parse, the service does not
start, and what you see is not a parse error. It is a container stuck in `Created`, or a job
reporting exit 0 having done nothing, or three hours of looking at the wrong thing.

This checks the file before the service does. It runs at the moment the file is written, so the
broken state never exists.

## What it costs

A parse of one file per Write or Edit, on files with six extensions. Milliseconds. It runs in
process on PreToolUse and touches no network.

The sweep reads 747 files once a day inside a job that already runs. No money, no network.

## What it watches or changes

The guard watches every Write and Edit any session makes. It refuses the ones that would leave a
`.xml`, `.yml`, `.yaml`, `.json`, `.jsonc` or `.toml` file unparseable by its own consumer. It
changes nothing else and never rewrites your content.

The sweep watches and changes nothing. It counts what is already broken and separates two numbers.
`known` is on the baseline in `config-syntax-baseline.txt`, with a reason recorded for each. `new`
is anything broken that is not, and that is the number that has to stay at zero.

## Where it lives

```
config_syntax.py             the parse routing, imported by both
config-syntax-guard.py       the PreToolUse refusal
config-syntax-sweep.py       the count, read-only
config-syntax-baseline.txt   the five already-broken files and why each is there
```

The routing lives in one file on purpose. If the guard and the sweep each had their own idea of
"broken" they would disagree, and a file the sweep calls clean would be one the guard refuses.

## How to turn it off

Remove `config-syntax-guard.py` from the PreToolUse block in `~/.claude/settings.json`, and unload
the sweep:

```
launchctl bootout gui/$(id -u)/com.founder.configsyntaxsweep
```

Do both or neither. A live refusal with no count behind it protects the next file and tells you
nothing about the ones already broken, and a count with no refusal watches the number grow.

## How to turn it back on

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.founder.configsyntaxsweep.plist
```

and restore the settings.json entry.

## What goes wrong

**It refuses correct work.** This is the failure that matters, because a guard that refuses correct
work is an outage. The parse is the one the consumer performs and nothing stricter. A YAML file with
tabs a real parser accepts is accepted here. If you hit a refusal you believe is wrong, the selftest
is 19 cases and 5 of them exist to prove it allows things.

**A file it cannot classify.** An unknown extension is not graded and is not counted as clean. It is
reported as `blind`, because a guard that loses its evidence reports BLIND and never a verdict.

**The baseline hides a regression.** It cannot. The baseline is keyed to a file path, and a file
that becomes broken in a new way still parses as broken. The selftest proves exactly this with
`new_when_a_sixth_appears`.
