# Demo — ticket-gate

Every agent session carries a GitHub issue. It opens the issue itself, from the founder's own
words, the first time that session changes a file. Nobody types anything.

## A session with no ticket edits a file

```
$ printf '{"session_id":"d7dfd2d4-...","tool_name":"Edit","tool_input":{},
           "cwd":"/Users/chidionyema/.claude/scripts",
           "transcript_path":"~/.claude/projects/-Users-chidionyema/d7dfd2d4-....jsonl"}' \
    | python3 ~/.claude/scripts/ticket-gate.py
  hook exit=0 (must be 0, it never blocks the first call)
```

The hook returned immediately and let the edit through. A detached child went to GitHub.

## Two seconds later, the issue exists

Angle one, the bind file this machine wrote:

```
$ cat ~/.claude/state/tickets/d7dfd2d4-8c4e-4c11-b1a0-a3643af6c41d.json
  issue #46  i need you to listen in as a spy to all active sessions and conpile a list of is
  error: none
```

Angle two, GitHub itself, which can fail differently from the local file:

```
$ gh issue view 46 --repo chidionyema/crew
  #46 i need you to listen in as a spy to all active sessions and conpile a list of issues fo... [triage]
```

The title is what the founder actually typed when he opened that tab. Nothing was invented and
nothing was asked for.

## What he sees on his phone

Aiden already messages him every five minutes. Session lines now carry the issue number, so a
status line names the thread instead of leaving him to remember which tab held it:

```
$ python3 -c "...aiden.alerts(24)"
  9 alerts
    WAITING  #46 -Users-chidionyema for 11 min: WORKING: The rescue is running...
  ticket_of('d7dfd2d4-8c4e-4c11-b1a0-a3643af6c41d') -> '#46 '
```

## Tickets moving, on his phone

Two issues were opened for real at 20:48Z. The next tick saw the counts change and sent, and
Telegram handed back a message id:

```
$ /usr/bin/python3 ~/.claude/scripts/aiden/tick.py
{"at": "2026-08-23T20:48:53Z", "alerts": 9, "sent": 0,
 "delivery": {"ok": true, "message_id": 12916, "why": ""}, "took_s": 12.7}

$ cat ~/.claude/state/aiden-ticket-counts.json
{"open": 26, "moved_24h": 20, "closed_24h": 0, "stuck": 6}      # was 24 / 18 / 0 / 6
```

The tick before it, with the same alerts and no ticket movement, sent nothing:

```
{"at": "2026-08-23T20:48:13Z", "alerts": 9, "sent": 0,
 "delivery": {"ok": true, "why": "nothing needed a person"}, "took_s": 9.5}
```

## The page

```
$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/ops
200
$ curl -s http://127.0.0.1:8787/ops | grep -o "[0-9]* open &middot; [0-9]* moved in 24h &middot; [0-9]* closed in 24h"
24 open &middot; 18 moved in 24h &middot; 0 closed in 24h
```

## The refusal, when GitHub will not take the issue

```
$ printf '{"session_id":"probe2","tool_name":"Edit",...}' | python3 ticket-gate.py
TICKET GATE: this session has no GitHub issue and opening one failed.
  gh: could not authenticate
No work happens off the board (founder, 2026-08-23: "it should be impossible to work without a ticket").
Open one, then retry:  crew-triage  (or gh issue create --repo chidionyema/crew)
  exit=2
```

Exit 2 stops the tool call. The message lands on the agent, never on the founder.

## The decision table, proved without touching the network

```
$ python3 ticket-gate.py --selftest
selftest: 15/15 passed
```

Reads pass, writes need a ticket. `grep`, `ls` and `cat x | head` are reading. `git commit`,
`git push`, `fly deploy`, `rm`, and any `>` redirect are writing.

## Who is working on what, right now

```
$ python3 ticket-gate.py --roster
IDLE   WHERE                TICKET  WHAT HE ASKED FOR
   0m  -Users-chidionyema   #46     i need you to listen in as a spy to all active sessions
  98m  subagents            NONE
 133m  ector-cli-cwd-slot-0 NONE

25 live session(s), 25 with no ticket
```

That run was taken before the gate was wired in. NONE means the session has only been reading;
it binds the moment it changes anything.
