# friction-relay — onboarding

**What it is for.** You say something to one agent. The other five never find out, so they
ask you again or keep doing the thing you just objected to. This carries what you said to
all of them.

**What it costs.** One transcript scan every 10 minutes, niced to 10. Nothing leaves the
machine. No API calls, no money.

**What it watches.** Your own messages in the last 6 hours, across every session, filtered
to the ones that read as friction. It shows at most 6 and says how many more there were.

**Where it lives.** `~/.claude/scripts/friction-relay.py`. Cache at
`~/.claude/state/friction-relay.json`. Job `ai.estate.friction-relay`. Logs in
`~/.claude/state/logs/friction-relay.{out,err}`.

**How to stop it.**

```
launchctl bootout gui/$(id -u)/ai.estate.friction-relay
```

**How to start it again.**

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.estate.friction-relay.plist
```

**What goes wrong.** If the cache is more than 15 minutes old the hook stays silent rather
than showing you stale complaints as if they were current. If the background refresh cannot
start, it writes a broken-guard row rather than failing quietly.
