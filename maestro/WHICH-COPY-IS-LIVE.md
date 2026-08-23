# The live maestro is ~/dev/code/maestro

There are two copies of maestro on this machine and they open the same database
(`~/.maestro/experience_graph.db`, `models.py:40` here and `maestro.py:40` there).
Running both would have two processes writing one graph.

The one that runs is `~/dev/code/maestro`, under launchd job
`com.chidionyema.maestro`. It carries the spec the estate certifies it against
(`docs/MAESTRO-DEPUTY-v1.0.md`), its claim ledger (`REQUIREMENTS.jsonl`), its
probes (`bin/maestro-cert`) and its tests, and it had commits on 2026-08-23.

This directory is a module split of the 2026-08-22 monolith and nothing starts
it. Its launchd plist has been renamed `.SUPERSEDED-2026-08-23` so it cannot be
bootstrapped by accident. Nothing is deleted; it is all in git history.

Merging the split back into the live copy is worth doing and is not urgent. It
is not this file's job to decide that.
