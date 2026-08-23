# law-writer — onboarding

**What it is for.** You asked for laws that write themselves from real incidents, your own
complaints and repeated mistakes, instead of laws someone sat down and imagined. This is
that. Your 32 hand-written laws in `~/AGENTS.md` are the static tier and win every tie; this
is the dynamic tier underneath them.

**What it costs.** One transcript scan an hour, niced to 10. Nothing leaves the machine.

**What it watches.** Guard refusals in transcripts, your complaints from friction-relay, and
guards that reported themselves broken. It ranks by cost: an instrument that went blind or
a thing you said outranks a frequent cheap annoyance. Below a cost of 3 a law is dropped
automatically, so the list shrinks as the estate gets better. There is no extend-anyway
branch, because a sunset clause with an escape hatch never sunsets anything.

**Where it lives.** `~/.claude/scripts/law-writer.py`. Output at `~/.claude/LAWS.dynamic.md`.
Job `ai.estate.law-writer`. Logs in `~/.claude/state/logs/law-writer.{out,err}`. It reaches
sessions through `memory-loop.py`, in the same block as the static laws, not as its own hook.

**How to stop it.**

```
launchctl bootout gui/$(id -u)/ai.estate.law-writer
```

**How to start it again.**

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.estate.law-writer.plist
```

**What goes wrong.** The hook never rebuilds; it only reads the cache, and stays silent if
the cache is over 6 hours old. If the cache is fresh but nothing parses out of it, that is a
broken parser and it writes a broken-guard row rather than reading as an empty estate.
