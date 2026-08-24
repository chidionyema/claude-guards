# Config syntax — what it looks like when it runs

A double hyphen inside an XML comment is illegal. One went into
`idp/observability/clickhouse-low-memory.xml` on 2026-08-24, so ClickHouse refused the whole file
with `SAXParseException: Invalid token` and crash-looped. `langfuse-web` and `langfuse-worker` have
a `depends_on` condition on clickhouse being healthy, so neither was ever created. `docker ps -a`
showed them as `Created`, which reads like "not started yet" rather than "blocked upstream". Three
hours went into that. The comment written to explain the fix contained a second double hyphen and
broke the file again.

The class is not "an XML comment". It is a config file a service reads at startup, whose syntax
nothing checks before that service starts.

## The refusal, live

`config-syntax-guard.py` runs on PreToolUse. Every session writes files through Write and Edit, so
every session goes through it. A write that would leave a `.xml`, `.yml`, `.yaml`, `.json`, `.jsonc`
or `.toml` file in a state its own consumer cannot parse is refused before it lands.

```
$ python3 config-syntax-guard.py --selftest
19/19 passed
```

## The present, counted

A guard is a promise about the future. The sweep prints how broken the present already is, which is
LAW 45 step 4 and the whole of the word "exhaustively".

```
$ python3 config-syntax-sweep.py
checked=747  broken=5  new=0  known=5  blind=0
KNOWN   /Users/chidionyema/dev/code/QAlgo/src/api/data/opt_neta.json
        JSONDecodeError: Extra data: line 25 column 1 (char 561)
KNOWN   /Users/chidionyema/dev/code/QAlgo/src/api/data/cat.json
        JSONDecodeError: Extra data: line 12 column 3 (char 185)
KNOWN   /Users/chidionyema/dev/code/QAlgo/src/api/data/nod.json
        JSONDecodeError: Extra data: line 156 column 1 (char 3035)
KNOWN   /Users/chidionyema/dev/code/QAlgo/src/api/data/nod_neta.json
        JSONDecodeError: Expecting value: line 6 column 1 (char 5)
KNOWN   /Users/chidionyema/dev/code/QAlgo/src/api/data/nod_attr.json
        JSONDecodeError: Extra data: line 156 column 1 (char 3035)
```

747 config files on this machine. Five cannot be parsed by the thing that reads them, and all five
were already broken before the guard existed. They are JavaScript source and concatenated JSON
documents saved with a `.json` extension. `nod_attr.json` is loaded by `src/api/run.py:646` and
`src/api/auth2.py:239`, so that application has been broken at runtime since the repo's last commit
on 2023-11-23. Repairing them means choosing which of the concatenated documents the application
should get, which is a product call in a repo nobody runs.

That is why they are `KNOWN` and not `new`. The number that matters is `new=0`.

## The control

```
$ python3 config-syntax-sweep.py --selftest
checked=5 broken=['bad.xml'] blind=0
baselined=1 new_after_baseline=0
new_when_a_sixth_appears=['second.xml']
PASS
```

Three claims, proved in one run. It finds a broken file. A file on the baseline stops counting as
new. A newly broken file still counts, so the baseline silences the past without blinding the
future.

## Why one parser and not two

`config_syntax.py` holds the routing, and both the guard and the sweep import it. Two
implementations of one check is the failure LAW 3 names: the scheduled sweep and the live refusal
would drift, and then a file the sweep calls clean is one the guard refuses.
