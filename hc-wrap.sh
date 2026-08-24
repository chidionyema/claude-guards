#!/bin/sh
# hc-wrap.sh <slug> <command...> — run a scheduled job under Healthchecks dead-man monitoring.
#
# The receiver's address is configuration, not a constant. It was hardcoded to
# http://127.0.0.1:8000, which is the local container, which is inside the same
# failure domain as every job it watches: when the Mac stops, the jobs stop and
# so does the thing that would have said so. Measured 2026-08-24, that receiver
# answers HTTP 000, and 12 of 40 estate jobs were pinging it into nothing.
#
# Reading the base from one file makes the local container, healthchecks.io
# hosted, and a Healthchecks instance on a rented box the same one-line change.
# It is the same open-source ping protocol in all three, so there is an exit
# from any of them (LAW 19: portability outranks detection).
#
#   ~/.estate/healthchecks/base   the prefix before /<ping-key>/<slug>, no trailing slash
#   HC_BASE=...                   overrides the file, for a single run or a test
#
# The prefix, not the host, because the two deployments differ by a path segment
# and getting that wrong pings a 404 forever while every job reports success:
#   self-hosted   http://127.0.0.1:8000/ping/<key>/<slug>
#   hosted        https://hc-ping.com/<key>/<slug>
# (https://healthchecks.io/docs/http_api/, read 2026-08-24.)
#
# With neither set the default is the local container, so nothing changes for a
# job that was working before this line existed.
#
# If the receiver is down or the ping key is missing, the job still runs
# unchanged — the old monitoring scripts remain the fallback by founder order
# (2026-08-24, "but still retain the onces getting replaced as fallback").
# Exit status is always the wrapped job's own, never curl's.
#
# HC_PING_TIMEOUT is 3 seconds, not curl's default and not the 10 it was until
# 2026-08-24. A receiver that hangs rather than refuses costs every wrapped job
# the full timeout twice per run, and the local container does exactly that: it
# accepts the TCP connection and never answers. Measured across the 15 wrapped
# jobs and their schedules that was 14,480 seconds — 4.02 hours — of estate
# processes per day sitting in curl. ai.aiden.watch runs every 300 seconds and
# lost 20 of them.
#
# Three seconds because a ping is one small GET and a transatlantic round trip
# is under 200ms, so 3s is more than ten times any honest ping; and because a
# ping that is slower than that has already failed for the purpose — a missed
# ping IS the dead-man signal, and the next scheduled run sends another. The
# monitoring must never cost more than the thing it monitors.
HC_PING_TIMEOUT="${HC_PING_TIMEOUT:-3}"
#
# HC_FINDINGS_EXIT: the exit codes this job uses to mean "I ran fine and I found
# something", space-separated. Empty by default, which is exactly the behaviour
# every job had before this line existed. Opt in per job, never estate-wide.
#
# Why it exists. Measured 2026-08-24 across the 51 loaded jobs: 18 exited
# nonzero on their last run, 4 of them already wrapped. They are not broken.
# com.founder.lawenforcement prints "1 stream(s) silent >24h" and exits 1;
# com.founder.sciencecollect prints "1 store(s) in neither SOURCES nor DECLINED"
# and exits 1. Exiting nonzero to report a finding is correct for a guard.
#
# But a dead-man check asks one question — did this run when it should have —
# and answering it with the job's exit status conflates that with a second
# question, what did it find. A guard with an open finding would sit red on the
# board for as long as the finding is open. That is 35% of this estate, and a
# board that is a third permanently red is one nobody reads (LAW 28).
#
# The fix does not map a finding to success, because that would throw away the
# one signal that says a job actually crashed. It splits the two questions into
# two checks:
#
#   <slug>            liveness. Green whenever the job ran to completion.
#   <slug>-findings   findings. Fails when the job reports one, clears when it
#                     does not, so an open finding still alerts on its own check.
#
# A crash — any nonzero code NOT declared in HC_FINDINGS_EXIT — still fails the
# liveness check, which is what it should do.
HC_FINDINGS_EXIT="${HC_FINDINGS_EXIT:-}"
SLUG="$1"; shift
PK=$(cat "$HOME/.estate/healthchecks/ping_key" 2>/dev/null)
HC_BASE="${HC_BASE:-$(cat "$HOME/.estate/healthchecks/base" 2>/dev/null)}"
ROOT="${HC_BASE:-http://127.0.0.1:8000/ping}/$PK"
BASE="$ROOT/$SLUG"
ping() { [ -n "$PK" ] && curl -fsS -m "$HC_PING_TIMEOUT" -o /dev/null "$1" 2>/dev/null; }

ping "$BASE/start?create=1"
"$@"
RC=$?

# Is RC one of the codes this job declares as a finding? Word-matched against the
# list, so HC_FINDINGS_EXIT=1 does not also match 21 or 12.
IS_FINDING=no
for code in $HC_FINDINGS_EXIT; do
    [ "$code" = "$RC" ] && IS_FINDING=yes && break
done

if [ -n "$HC_FINDINGS_EXIT" ]; then
    # Opted in: liveness answers "did it run", findings answers "what did it find".
    # RC=0 pings the findings check as success too, so a finding that has been
    # resolved clears instead of staying red forever.
    if [ "$IS_FINDING" = yes ]; then
        ping "$BASE/0"
        ping "$ROOT/$SLUG-findings/fail?create=1"
    elif [ "$RC" = 0 ]; then
        ping "$BASE/0"
        ping "$ROOT/$SLUG-findings/0?create=1"
    else
        ping "$BASE/$RC"          # undeclared nonzero: a real crash, still red
    fi
else
    ping "$BASE/$RC"              # unchanged for every job that has not opted in
fi
exit $RC
