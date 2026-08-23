# no-anthropic: the drill, running

Everything on this estate ran through one vendor. On 2026-08-23 the founder
called that the single biggest risk to the company's existence. This is the
command that answers whether it is still true, and what it said the first time
it ran for real.

## The command

```
python3 ~/.claude/scripts/drills/no_anthropic.py
```

It builds a throwaway directory, strips every Anthropic credential out of the
environment, and checks two separate things. A model answering a question is one.
Something reading a file, changing it, and the file being different afterwards is
the other, and only the second one is the founder's actual working pattern.

## What it printed

```
SUBSTRATE  a model answers at all
  PASS  openrouter            1.9s  PORTABLE
  PASS  groq                  0.7s  PORTABLE
  PASS  mistral               0.7s  Portable.
  FAIL  gemini                0.5s  Your prepayment credits are depleted.
  FAIL  deepseek              0.9s  Insufficient Balance
  FAIL  ollama                0.4s  said 'Ink\n', wanted PORTABLE

AGENT      something edits a file and proves it
  PASS  aider-mistral        12.2s  config.toml now says version = 2

3/6 substrate rails and 1/1 agent rails work with Anthropic switched off.
VERDICT: the estate can still work without Anthropic.
exit=0
```

The agent line is the one that matters. `aider` was pointed at Mistral's coding
model, handed a file saying `version = 1`, and told to make it say `version = 2`.
The drill does not believe the exit code and does not believe the model: it opens
the file afterwards and looks. That is deliberate, because on the same afternoon
both vendor CLIs exited 0 having changed nothing while printing a cheerful
paragraph about the work they had done.

That edit cost $0.00024.

## The same rails, now carrying live traffic

The consult daemon's cascade used to be two headless browsers holding logged-in
sessions, then a local model. Sessions expire at three in the morning and stay
expired until a person signs in. The keyed rails now go first:

```
$ consultd.py backends
cascade in use: groq -> mistral -> openrouter -> kimi-bridge -> deepseek -> ollama

$ curl -s -X POST -H "Authorization: $TOKEN" \
    -d '{"question":"Reply with exactly one word: INDEPENDENT"}' \
    http://127.0.0.1:8765/consult
  status  : success
  backend : groq    0.52 s
  answer  : 'INDEPENDENT'
```

Answered in half a second by the free tier, which is the rail that keeps working
when there is no money in any account at all.

## Registered, so it goes red on its own

```
$ python3 ~/.claude/scripts/drills/run.py --list
drill                    status       detail
  no-anthropic           PASS         0.0d ago
  rebuild                PASS         0.0d ago
  estate-bundle-restore  PASS         0.0d ago
```

It runs at 04:30 every morning under `ai.estate.drills` and posts one line to the
board that every session reads at startup. Two days without a green and it reads
STALE rather than silent, because a dead checker and a healthy estate produce the
same silence and only one of them is good news.
