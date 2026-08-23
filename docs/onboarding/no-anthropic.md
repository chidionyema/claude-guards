# no-anthropic

## What this is for

If Anthropic goes down, suspends the account, or raises prices past what this
company can pay, every agent working on this estate stops at the same moment.
That is the risk this exists to take away. It does not remove the dependency,
which would mean rebuilding everything; it proves there is a door, checks the
door still opens every morning, and tells you the day it stops opening.

## What it costs

Close to nothing. One run makes three small API calls and one file edit, and the
edit that proves the whole thing works cost $0.00024. It runs once a day. Call it
a cent a month.

The rails it depends on cost differently, and this is the part worth knowing:

- **groq** is a free tier. No money in any account and this one still answers. It
  is deliberately first in every cascade for that reason.
- **mistral** is paid and has credit. It did the file edit.
- **openrouter** is one key that reaches 422 models across Anthropic, OpenAI,
  Google, DeepSeek, Qwen and Mistral. It is the broadest exit available and its
  balance was **minus seventeen cents** on 2026-08-23. It answers small questions
  on the dregs and will stop. Ten dollars there buys the widest door this estate
  has, and that is a spend decision, so nobody has made it.
- **ollama** runs on this Mac and needs no account and no network at all.

Two rails are already dead and stay dead until someone pays: Google's API says
its prepayment credits are depleted, DeepSeek says insufficient balance.

## What it watches

Two layers, because they break for different reasons.

**Substrate** is whether a model will answer a question. Six rails, and it names
each one that fails and why in the failure's own words.

**Agent** is whether anything can read a file, change it, and leave it changed.
This is the layer the working pattern actually sits on, and a chat completion is
not a substitute for it. The drill passes only when the file on disk is different
in the exact way it asked for. It does not trust the exit code, because both
vendor CLIs on this machine have exited 0 having done nothing at all.

## Where it lives

```
~/.claude/scripts/drills/no_anthropic.py     the drill
~/.claude/scripts/drills/register.json       its entry, 2-day freshness bar
~/.claude/scripts/direct_api_backends.py     the three keyed rails
~/.claude/scripts/consultd.py                the cascade that now uses them
~/Library/LaunchAgents/ai.estate.drills.plist  runs 04:30 daily
~/.claude/state/drills.jsonl                 every run ever, append only
```

Keys come from `~/.config/llm/secrets.sh`, mode 0600. That matters more than it
looks: a scheduled job gets no interactive shell, so a key that only lives in
`.zshrc` is invisible to it. The free rail was in exactly that state and every
scheduled run would have reported it dead.

## How to turn it off

```
launchctl bootout gui/501/ai.estate.drills
```

That stops all the recovery drills, not just this one. To stop only this one,
set its `cmd` to `null` in `register.json` and it reports NOT WRITTEN instead of
running.

## How to turn it back on

```
launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.estate.drills.plist
```

## What goes wrong

**It reports a rail dead that you know works.** Almost always the key is in your
shell and not in `~/.config/llm/secrets.sh`. The daemon and the schedule read the
file; only you read the shell.

**A rail answers nothing at all.** Groq's models think before they speak and spend
the token budget doing it, so a tight cap returns an empty answer that looks
exactly like a dead key. The cap is 2000 tokens for that reason.

**Everything passes and you still cannot work.** The drill proves an exit exists.
It does not promise the alternative is as good, and nobody has measured that. What
it buys is a day where work continues instead of stopping, which is the difference
between an inconvenience and the end of the company.

## Agent rails that do not work, and why, so nobody tests them again

Measured 2026-08-23. Both were tried on every auth path available on this machine.

**cursor-agent** stops before it does anything: "Set a Spend Limit to continue
with Auto. Your usage limits will reset when your monthly cycle ends on
8/30/2026." That is a setting on the founder's Cursor account. No amount of
local configuration reaches it.

**gemini CLI** fails on both of its auth paths. With the API key it returns 429,
because `~/.gemini/settings.json` selects `gemini-api-key` and that key's account
reports its prepayment credits depleted. On the free personal OAuth tier
(`GEMINI_DEFAULT_AUTH_TYPE=oauth-personal`) it also returns 429 and leaves the
file unchanged at `version = 1`. Two different doors, one shut account.

Neither is a bug in the drill. Both become live rails the moment somebody puts
money or a spend limit behind them, and the drill will report them the next
morning without anyone editing it.

**aider on the free Groq rail does work, and it is rate limited.** It changed the
file to `version = 2`, having first been told to wait 32 seconds. A free tier
under load is slow, not absent. Treat it as the rail that keeps working when the
paid ones stop, not as the fast one.
