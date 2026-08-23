# Onboarding — ticket-gate

## What this is for

You prompt several agent tabs at once. Work gets started in one of them and nobody follows it up,
because the only record that it was ever asked for is the tab you typed it into. You asked a
session to get aiden operational; no issue was ever opened; by the time you asked again, nobody
could say which tab held it. Aiden had in fact been running the whole time.

This makes that impossible. Every session that changes anything carries a GitHub issue on
`chidionyema/crew`, and the issue is opened automatically from your own first words in that tab.

## What it costs you

Nothing to run and nothing to remember. There is no command for you here. The issue appears by
itself, the ticket number rides along on the Aiden message that already reaches your phone every
five minutes, and it shows on the ops dashboard.

You see tickets moving in two places. Telegram sends a line the moment the numbers change — a
ticket opened, a ticket closed, a ticket gone quiet for a day — and stays silent when the board
did not move, so a message always means something happened. The page at
`http://127.0.0.1:8787/ops` carries the same four numbers and the full list, newest movement
first, whether or not anything changed.

In machine terms it costs about ten milliseconds on a tool call, once per session, plus one
`gh issue create` in a background process that no agent waits for.

## What it watches, and what it changes

It watches tool calls that change the world: `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, and any
Bash command that writes — commit, push, deploy, `rm`, a `>` redirect. Reading is never touched, so
an agent looking at a file or grepping for a symbol is not interrupted.

It changes two things. It opens one GitHub issue per session, labelled `triage`, titled with what
you typed. And it refuses a change when a session has no issue and opening one failed.

## Where it lives

- The gate: `~/.claude/scripts/ticket-gate.py`, in the `claude-guards` repository.
- The bindings: `~/.claude/state/tickets/<session>.json`, one small file per session.
- The wiring: `~/.claude/settings.json`, under `PreToolUse`.
- The issues: `github.com/chidionyema/crew/issues`.

## How to turn it off

One command, and it stops everywhere on this machine at once:

```
python3 ~/.claude/scripts/ticket-gate.py --off
```

That removes the two hook entries from `settings.json` and takes effect on the next tool call in
every session. No restart. Nothing else on the estate depends on it.

## How to turn it back on

```
python3 ~/.claude/scripts/ticket-gate.py --on
```

## What goes wrong

**GitHub is down or `gh` loses its login.** The first session to try gets a failed binding, and
its next change is refused with a message telling the agent to open an issue by hand. Nothing is
lost and nothing is silently allowed through. Aiden raises `NO TICKET` on your phone, so you learn
about it without going anywhere.

**A session only reads.** It never binds and never shows a ticket. That is correct: a tab that has
only looked at files has not started work that could go missing.

**Two agents in one session.** They share the issue, which is right, because you asked one tab for
one thing.

**The gate itself breaks.** It exits 0 and the estate keeps working. A guard that wedges fifteen
live sessions because of its own bug is worse than the problem it was written for.
