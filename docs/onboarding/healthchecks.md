# Onboarding: Healthchecks job monitoring

## What is this for

Your scheduled jobs could die silently: a job that stops running sends no error,
because nothing is left alive to send one. The old hand-built monitor scripts only
alert on failure, so silence could mean "all fine" or "the checker itself is dead" —
and you could not tell which. Healthchecks is a dead-man's switch: every wired job
must check in on schedule, and a missed check-in becomes a 🔴 Telegram message on
your phone. It tells PASS apart from NOT-RUN, which nothing else on the estate did.

## What does it cost

Nothing in money. It is open-source software (BSD licence) running in a container on
this Mac. Nothing leaves the machine except the alert to Telegram. It uses a small
slice of memory under colima, which now starts itself at login.

## What does it watch or change

It watches wired scheduled jobs (first: the hourly estate snapshot; more being added
in batches). It changes nothing about the jobs themselves — a thin wrapper
(`hc-wrap.sh`) pings the monitor before and after each run. If the monitor is down,
the job still runs exactly as before. All the old monitoring scripts are untouched
and still running, as you ordered — this sits in front of them, it replaces nothing
destructively.

## Where it lives

- The service: docker container `estate-healthchecks`, reachable only from this Mac
  at http://127.0.0.1:8000 (nothing outside the machine can see it).
- Its data and keys: `~/.estate/healthchecks/` (owner-only permissions).
- The wrapper: `~/.claude/scripts/hc-wrap.sh`, in git.

## How do I turn it off

One command stops it and all its alerts:

    docker stop estate-healthchecks

Every wired job keeps running unchanged; you are simply back to the old monitoring.

## How do I turn it back on

    docker start estate-healthchecks

## What goes wrong

- After a reboot the container waits for colima (the docker runtime) to start;
  colima is registered as a login service, so this is automatic but takes a minute
  or two.
- If the monitor itself dies you get no "monitor is down" message from it — that is
  the one silence it cannot cover about itself. The old scripts still run as the
  second layer, and a watchdog for the monitor is on the list.
- A wired job that gets slower than its schedule window will false-alarm; the fix is
  raising that check's grace time, not ignoring the alert.

## Alerts (added 2026-08-24)

- When any of the 35 checks goes down or recovers, a Telegram message arrives on
  your phone. You do nothing to fetch it.
- Turn alerts off: `docker exec estate-healthchecks python manage.py shell -c "from hc.api.models import Channel; Channel.objects.filter(kind='apprise').delete()"`
- Turn back on: rerun the channel setup (recorded in this repo's history); the
  container recreate command is `estate/healthchecks-run.sh`.
- The bot token is read from ~/.config/estate/estate.env and never committed.
