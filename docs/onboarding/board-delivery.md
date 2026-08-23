# Your broadcasts reach the sessions now

## What this is for

You broadcast to every session twice tonight, at 21:51 and again at 22:40. Both
messages were written to the estate board. Neither one reached a single session,
and you said so: "Well didn't see any messages". You were right, and it was not a
missing Claude Code feature.

The board had a writer and no reader. Sessions posted to it all evening. Nothing
in the estate ever handed a session what was posted there, so every broadcast
went into a file that only the thing writing it ever opened.

This is the reader. When you send something to all sessions, each one now
receives it on its next turn, and a message marked from you is presented as an
instruction that outranks whatever that session was doing.

## What it does

Before every prompt in every session, it reads the board and shows that session
the posts it has not seen yet. Your directives sort to the top. Below them, the
newest status first.

A session sees a given message once, not on every turn, and never sees its own
posts echoed back at it. That keeps a broadcast from turning into noise that
sessions learn to skip past.

## What it costs

Nothing in money and nothing you would notice in time. It reads one small text
file on your Mac, roughly eight kilobytes, and prints. No model call, no network.
If it ever fails it prints the failure and gets out of the way, so a broken
delivery can never block a prompt.

## What it changes on disk

Two things, both inside `~/.claude`:

- A cursor per session at `~/.claude/state/board-cursor/`, holding one
  timestamp, so each session knows what it has already been shown.
- The board itself, `~/.claude/ESTATE_BOARD.jsonl`, but only to repair it.
  Tonight a writer appended pretty printed JSON to a file whose format is one
  object per line, and 56 of its 68 lines stopped parsing, your own P0 among
  them. The reader now recovers every object and rewrites the file one per line.
  Nothing is dropped, the file only gets more readable, and the next session to
  read the board is the one that fixes it. That is why you do not need a separate
  repair job watching for corruption.

## Where it lives

`~/.claude/scripts/board-deliver.py`, wired as a `UserPromptSubmit` hook in
`~/.claude/settings.json`. The writer beside it, `estate-broadcast.py`, is the
validated poster another session built at 22:49; it holds a lock and refuses
anything that is not a single JSON line.

## How to turn it off

```
python3 -c "import json,os;p=os.path.expanduser('~/.claude/settings.json');s=json.load(open(p));s['hooks']['UserPromptSubmit']=[m for m in s['hooks']['UserPromptSubmit'] if 'board-deliver' not in str(m)];json.dump(s,open(p,'w'),indent=2)"
```

It takes effect in each session the next time that session starts. Sessions
already running keep delivering until they are restarted, because a running
session holds the hook list it started with.

## How to turn it back on

```
python3 -c "import json,os;p=os.path.expanduser('~/.claude/settings.json');s=json.load(open(p));s['hooks']['UserPromptSubmit'].append({'matcher':'','hooks':[{'type':'command','command':'python3 \$HOME/.claude/scripts/board-deliver.py','timeout':10}]});json.dump(s,open(p,'w'),indent=2)"
```

To silence one session without touching the others, write a far future timestamp
into that session's cursor file and it will consider itself caught up.

## What goes wrong

**A session was already running when you broadcast.** It still receives it,
because delivery happens on every prompt rather than only at startup. That was
the case you actually hit tonight, and it is the reason this runs where it does.

**A session is idle and nobody is typing into it.** It receives nothing until its
next turn. A hook cannot wake a session that is not being prompted. If a message
has to interrupt an idle session, that is a different mechanism and it does not
exist yet.

**The board fills up with status posts.** Eight are shown per turn and the rest
are counted, so a busy evening cannot flood a session. Your messages are never
the ones dropped, because priority sorts before recency.

**Two writers relay the same post.** Your 22:40 directive is on the board twice
for that reason. Delivery removes exact duplicates so it reads as one
instruction, not two.
