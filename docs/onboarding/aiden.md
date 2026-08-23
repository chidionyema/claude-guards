# Aiden, onboarding

## What it is for

Six Claude Code sessions share this machine and none of them can see the others.
Aiden is the one thing that sees all of them. It reads the transcript files
Claude Code already writes and turns them into a state the founder can read at
any moment without running anything.

## What it costs

Nothing per watch. The version that arrived in the zip called `claude -p` every
five seconds for every project, which is 17,280 model calls per project per day
and about $7,188 a day for four projects. This one makes zero model calls. Its
only subprocess is `hermes send`, which reuses the gateway's existing Telegram
credentials. The whole cost is about twelve seconds of one CPU core every five
minutes, at nice 10.

## What it watches for

BLOCKED, a session asked a question and nobody has answered it.
WAITING, a session has been idle for more than ten minutes mid task.
CHURN, a session keeps starting cold and paying for a cache it never reads back.
BURN, spend crossed forty dollars an hour.
UNREAD, Aiden itself could not read something, which is reported rather than
swallowed.

## Where it lives

```
~/.claude/scripts/aiden/observe.py   the transcript folder, no model calls
~/.claude/scripts/aiden/aiden.py     board, cost, alerts, html
~/.claude/scripts/aiden/tick.py      one cycle: read, alert, deliver, record
~/.claude/state/aiden-board.html     the page, rewritten every cycle
~/.claude/state/aiden-ticks.jsonl    one line per cycle, including quiet ones
~/Library/LaunchAgents/ai.aiden.watch.plist
```

## How to turn it off

```
launchctl bootout gui/501/ai.aiden.watch
```

That is the whole undo. Nothing else on the machine depends on it, the board
file simply stops being updated, and the transcripts it reads are written by
Claude Code whether Aiden runs or not.

## How to turn it back on

```
launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.aiden.watch.plist
```

## What can go wrong

If Telegram cannot be reached, or hands back no message number, the cycle writes
the reason into its own line rather than dropping it, and the alerts stay
unsaid so the next cycle offers them again. If a transcript is unreadable, the
file is named in an UNREAD alert. Repeated alerts are collapsed by a fingerprint
that ignores digits, so "waiting 12 min" and "waiting 40 min" are one alert and
not two, and nothing is resent inside a six hour quiet window.

Almost nothing reached the founder for two hours on 2026-08-23, and two separate
faults caused it. Counted across the 32 cycles logged that day: 12 cycles were
killed at their four minute limit while reading the transcript files and never
got as far as sending; 3 cycles tried to send and the send failed; 1 send got
through, at 19:30; 13 cycles had nothing to say.

The slow half was reading the same transcript tree twice per cycle, once for the
board and once for the alerts. It now reads it once, and a cycle takes 14 to 16
seconds instead of 66 to 168.

The failing-send half was the delivery route. It used to go through the Hermes
command line tool, which reads its settings from `~/.hermes`. That path is a
shortcut into `~/Documents`, and macOS hides `~/Documents` from a background job,
so the tool could not read its own settings. Delivery now goes straight to
Telegram using a credentials file outside `~/Documents`.

A third fault made both worse: a failed cycle marked its alerts as already said,
so each failure silenced itself for six hours. An alert now counts as said only
once Telegram has given back a message number.
