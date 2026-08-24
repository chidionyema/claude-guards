#!/bin/sh
# hc-wrap.sh <slug> <command...> — run a scheduled job under Healthchecks dead-man monitoring.
# Pings http://127.0.0.1:8000 (local Healthchecks container, estate-healthchecks) before and
# after the job. If Healthchecks is down or the ping key is missing, the job still runs
# unchanged — the old monitoring scripts remain the fallback by founder order (2026-08-24,
# "but still retain the onces getting replaced as fallback").
# Exit status is always the wrapped job's own, never curl's.
SLUG="$1"; shift
PK=$(cat "$HOME/.estate/healthchecks/ping_key" 2>/dev/null)
BASE="http://127.0.0.1:8000/ping/$PK/$SLUG"
[ -n "$PK" ] && curl -fsS -m 10 -o /dev/null "$BASE/start?create=1" 2>/dev/null
"$@"
RC=$?
[ -n "$PK" ] && curl -fsS -m 10 -o /dev/null "$BASE/$RC" 2>/dev/null
exit $RC
