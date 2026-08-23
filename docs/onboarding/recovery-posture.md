# recovery-posture

## What it is for

You said it plainly on 2026-08-23: if you disappeared today, the estate should
be able to run itself. Running itself means the scheduled jobs keep getting
their turns without anybody watching. Nothing here was measuring that.

Every other instrument on this Mac grades a job's *output* — was the file fresh,
did the command exit 0. All of those are downstream of the job getting a turn at
all. A job that never runs produces no output to grade, and `launchctl list`
reports exit 0 for it, so it looks identical to a job that is behaving.

This drill grades the turn, not the output. It is the answer to "is anything
quietly not running".

## What it costs

Under a second, once a day. It reads plist files, `launchctl list` and
`~/.estate/state/gate.log`. It writes nothing and changes nothing.

## What it watches

Forty-one job definitions, and six ways one of them stops being able to recover
itself:

1. Its program is not on disk. The job runs, the shell cannot find the file, and
   it exits without doing anything.
2. It has no KeepAlive, no RunAtLoad and no interval. It ran once when it was
   installed and nothing will ever run it again.
3. It is a live service with no KeepAlive, so the first crash is permanent until
   the machine reboots.
4. It sits behind `estate-gate` and never gets a turn.
5. It is loaded in launchd with no plist on disk, so it dies at the next reboot
   and nothing brings it back.
6. Its plist is on disk and it is not loaded, so it is already not running.

A job you have deliberately parked is not a fault, but it has to say so. There
is one, `ai.hermes.gateway`, and the reason is in the RETIRED block at the top of
the script. Anything else missing from launchd is treated as an accident.

## Where it lives

- The check: `~/.claude/scripts/drills/check_recovery_posture.py`
- Its entry in the register: `~/.claude/scripts/drills/register.json`, id
  `recovery-posture`
- What it reads: `~/Library/LaunchAgents`, `/Library/LaunchAgents`,
  `/Library/LaunchDaemons`, and `~/.estate/state/`

It is one of the drills, so it runs and reports exactly the way the other twelve
do. `docs/onboarding/drills.md` covers that machinery.

## How to turn it off

```
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path.home() / ".claude/scripts/drills/register.json"
d = json.loads(p.read_text())
d["drills"] = [x for x in d["drills"] if x["id"] != "recovery-posture"]
p.write_text(json.dumps(d, indent=1))
EOF
```

That removes it from the register and nothing else on the machine refers to it.

## How to turn it back on

`git checkout ~/.claude/scripts/drills/register.json` in the `claude-guards`
repository, which restores the entry.

## What goes wrong

**It reports a job cannot recover and the job is fine.** The likeliest cause is
the one that already happened once: the job is in the middle of a long run. The
drill checks for a live gate process before deciding, but a job that runs
without the gate and takes longer than three of its own intervals will be called
stale. Read `~/.estate/state/gate.log` for the job's own last line before
believing the drill.

**It passes and a job is still not doing its work.** This drill only says the
job got its turn. Whether the work inside it succeeded is what the job's own
exit code and the other drills are for. A job can run perfectly on schedule and
do nothing useful, and that is a different failure with a different instrument.

**It finds a job loaded with no plist.** That job survives only until the next
reboot. Nothing here writes the missing plist, on purpose: an agent guessing at
a job definition is how a wrong one gets installed permanently.
