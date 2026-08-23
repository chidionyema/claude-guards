# Aiden, demo

Aiden watches every Claude Code session on this machine and tells the founder
when one is stuck, burning money, or waiting on him. It makes no model calls at
all, so watching costs nothing.

## What he sees

A Telegram message arrives only when something needs him. Nothing arrives when
the estate is fine.

```
Aiden
BLOCKED  hermes-v2  asked a question 14 min ago and nobody answered
BURN     tie        $47.20/hour, above the $40 line
```

A board is always current at `~/.claude/state/aiden-board.html`, open it and it
shows every session from the last 24 hours: what it is doing, how long it has
been doing it, what it has spent, and how well it is reusing its cache.

## Run the demo

```
python3 ~/.claude/scripts/aiden/aiden.py board      # the table, right now
python3 ~/.claude/scripts/aiden/aiden.py cost 7     # what 7 days cost, by kind
python3 ~/.claude/scripts/aiden/aiden.py alerts     # what would be sent
python3 ~/.claude/scripts/aiden/tick.py             # one full cycle, board + send
```

A real run, taken 2026-08-23:

```
$ python3 ~/.claude/scripts/aiden/aiden.py cost 7
input        $3.56      0.1%
cache write  $1659.62   28.0%
cache read   $3166.27   53.4%
output       $1099.99   18.6%
total        $5929.44   over 7 days, $847.06/day
```

And the delivery receipt from the watcher's own log, which is the proof the
message arrived rather than the proof it was sent:

```
$ tail -1 ~/.claude/state/aiden-ticks.jsonl
{"at": "2026-08-23T20:08:00Z", "alerts": 9, "sent": 9,
 "delivery": {"ok": true, "message_id": 12903, "why": ""},
 "board": "/Users/chidionyema/.claude/state/aiden-board.html", "took_s": 15.5}
```

`message_id` is Telegram's own number for the message, handed back by its API.
It is the receipt, and it is the only thing the cycle is judged on. An exit code
says a program ended; it does not say a message arrived.

Asking Telegram whether that message really exists in the channel is the second
check, and it passed on the same run:

```
$ # editMessageText against id 12903
  telegram says: True
```

## What it just did

Every cycle appends one line to `~/.claude/state/aiden-ticks.jsonl` saying how
many alerts it found, how many it sent, and what the delivery returned. A cycle
that found nothing writes a line too, so a silent Aiden and a dead Aiden do not
look the same.
