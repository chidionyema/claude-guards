# Agent certification

Every agent this estate runs makes claims about itself. It says it watches
something, fixes something, learns something, reaches the founder. Until a
command proves one of those claims, it is a sentence in a README.

Certification is the standing answer. Each agent writes down what it claims, in
a form a machine can run. A scheduler runs all of it, grades the result, keeps
the score so it can be compared with last week's, and messages the founder when
a claim changes state. Nobody types a command to find out (LAW 31).

This is the process every new agent goes through. It is five steps and none of
them are optional.

---

## What a claim is

One line of `REQUIREMENTS.jsonl`, in the agent's own repository:

```json
{"id":"MAE-021","section":"§What This Actually Does","spec":"docs/MAESTRO-DEPUTY-v1.0.md","phase":"P1",
 "statement":"A message holding Markdown-unsafe text still reaches the founder, it is not dropped",
 "acceptance_cmd":"\"$MAESTRO_HOME/bin/maestro-cert\" telegram-unsafe-markdown",
 "status":"unknown","closed_by":null}
```

Two fields carry the weight.

`statement` is what the claim means, written so the founder can read it. Not
"REQ-021 passes". What the agent does, in his words where you have them.

`acceptance_cmd` is a shell command. Exit 0 means the claim is true right now.
Anything else means it is not. **An agent cannot close a row by asserting it is
closed** — that is the whole reason the ledger holds commands and not ticks.

`spec` and `section` point back at the document the claim came from, so a reader
can see whether the ledger covers what the spec promised or only the easy half.

`phase` groups claims. P1 is what makes the agent worth running at all. P2 is
what it promises beyond that.

`blocked_reason`, when present, moves a failing row out of the grade and into a
separate list. Blocked means waiting on a founder decision, not waiting on work.
It is reported to him and never alerted on. A row without a written reason cannot
be blocked, so "blocked" can never become a place to park failures.

### Writing a claim that is worth having

* **Test the promise, not the file.** `test -f maestro.py` proves a download
  happened. `bin/maestro-cert telegram-unsafe-markdown` proves a message with an
  unmatched underscore reached the founder's phone and came back with an id.
* **Check from outside the thing being checked.** A probe that imports the agent
  and asks it whether it is healthy is the agent restating its claim.
* **Include the claims that currently fail.** A ledger of things already working
  is a certificate the agent wrote for itself. Maestro's first ledger scored
  12 of 16 on purpose: shape extraction, skills and the approval path are
  claimed in its spec and are not there, and the score says so.
* **Never print a secret** (LAW 21). The Telegram probes print `ok=True` and a
  message id. They never print the token or the chat id.
* **Clean up after the probe.** The delivery check sends a real message, reads
  the `message_id` that proves it arrived, then deletes it. A check that runs
  hourly must not fill his chat with its own noise.

---

## The five steps of onboarding

**1. Read the agent's own spec and write the ledger from it.**
Not from the code. The code is what it does; the spec is what it claimed, and
the gap between them is the entire point of certifying. Cite the section in
every row.

**2. Write the probes the ledger calls.**
Anything that cannot be a one-line shell test goes in the agent's own
`bin/<name>-cert`, one subcommand per probe, each exiting 0 or non-zero. Keeping
them in the agent's repository means the claims travel with the agent (LAW 19).

**3. Register the agent.**
Add it to `agents.json` next to this file:

```json
{"name":"maestro","home":"~/dev/code/maestro","ledger":"REQUIREMENTS.jsonl",
 "home_env":"MAESTRO_HOME","onboarded":"2026-08-23","spec":"docs/MAESTRO-DEPUTY-v1.0.md"}
```

`home_env` is the variable its acceptance commands use to find themselves.
`AGENT_HOME` is exported as well, so a row can be written either way.

An agent in the registry with no ledger is graded `cannot be certified`. That is
a result, not a pass, and it is reported.

**4. Take the first grade and keep it.**
The first run is the baseline. It is appended to the history file, so every
later run can be compared against it and a regression is visible as a number
rather than a feeling.

**5. Put it in git** (LAW 24).
The ledger, the probes and the registry entry. A claim nobody can diff is a
claim that can be quietly softened until it passes.

---

## How grading works

`agent_cert.py` runs every acceptance command for every registered agent, each
with a 120-second ceiling, from the agent's own directory.

```
score = passed / (passed + failed)
```

Blocked rows are outside the denominator, reported separately. Timeouts count as
failures and are named, because a claim that cannot be measured in two minutes
is not a claim the founder can rely on.

Three files hold the result:

| file | what it is |
|---|---|
| `~/.claude/agent-cert/history.jsonl` | one line per agent per run, every row's state and output. This is the record a regression is proved against (LAW 30) |
| `~/.claude/agent-cert/status.json` | what the board reads: the score now, what is unproven, when it last ran |
| `~/.claude/agent-cert/last-green.txt` | when the last all-clear was sent, so green goes out once a day and not on every run |

`status.json` carries `last_run_at`. A board reading it can tell PASS from NOT
RUN, which a bare score cannot, and a dead checker looks exactly like a healthy
one until you can see that difference.

---

## How the founder hears about it

He does not run this. A launchd job does, and the result reaches him.

* **A claim broke** — a row that passed last run and fails now. Sent, with the
  requirement id and its statement.
* **A claim was fixed** — sent in the same message, so a repair is visible.
* **An agent joined** — its first run is always sent, so a new agent's real
  score arrives once rather than being absorbed into the baseline.
* **Nothing changed** — one message a day with the scores. Silence must never be
  the only signal, because silence is also what a dead checker sounds like
  (LAW 28).

Alerts fire on **transition**, not on state. An agent sitting at 12 of 16 does
not message him every hour about the same four rows. It messages him the hour
one of the twelve breaks.

---

## Running it by hand

There is a command, and it is for agents, not for the founder.

```
agent_cert.py                     # certify everything, message on change
agent_cert.py --agent maestro     # one agent
agent_cert.py --only P1           # one phase, section or requirement id
agent_cert.py --quiet             # no Telegram, for when a person is watching
agent_cert.py --strict            # exit 1 on any unproven claim, for a gate
agent_cert.py --json              # full scorecards
```

A filtered run (`--only`) is printed but not written to history or status. A
subset would otherwise read as every other claim having vanished.

---

## Why this does not replace hermes-v2's own checker

`~/dev/code/hermes-v2/bin/check-requirements.py` runs the same contract inside
that repository's CI, against that repository. It stays.

A repository's own gate must not depend on a file outside the repository, or it
goes red the day someone checks the code out on a different machine. The two are
the same job pointed at different targets, which LAW 19 calls the cost of being
able to leave. What is not allowed is a second grader with a second history and
a second score, and there is only one of those: this file's.
