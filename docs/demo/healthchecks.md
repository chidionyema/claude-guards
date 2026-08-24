# Demo: Healthchecks job monitoring

What you saw on your phone on 2026-08-24 at about 00:42 UTC was this system working:

> 🔴 canary-dead-man stopped running (missed its schedule)

and two minutes later:

> 🟢 canary-dead-man is running again

Nobody sent those by hand. A test job was pinged once and then deliberately left to
miss its schedule. The monitor noticed the silence and messaged you. That is the whole
product: a scheduled job that dies quietly now reaches your phone without any agent
being awake.

## The run that proved it

Check created and pinged once (00:40:32 UTC):

```
$ curl -d '{"name":"canary-dead-man","slug":"canary-dead-man","timeout":60,"grace":60,"channels":"*"}' \
    -H "X-Api-Key: ..." http://127.0.0.1:8000/api/v3/checks/
created: canary-dead-man | channels: e68b8017-9af1-4404-9ccd-72d83bb4be03
$ curl http://127.0.0.1:8000/ping/<ping-key>/canary-dead-man
OK
```

Two minutes of silence later, the monitor's own delivery ledger:

```
notification: 2026-08-24T00:42:33+00:00 | sent status: down | channel: telegram-webhook | error: ''
```

`error: ''` means Telegram accepted the message — matched by the 🔴 on your screen.

## A real job under the same watch

The hourly estate snapshot (the thing that rebuilds STATE.md) now runs wrapped:

```
$ curl -H "X-Api-Key: ..." http://127.0.0.1:8000/api/v3/checks/
estate-snapshot | status: up | last ping: 2026-08-24T00:43:54+00:00
```

If that job ever stops, your phone hears about it within about 75 minutes (its hourly
schedule plus 15 minutes of grace).

## Full coverage, 2026-08-24

Every scheduled job on this Mac is now under the watch — wrapped, or excluded with a
written reason (always-on services, Adobe/Steam vendor jobs, the Hermes reaper). The
board, read from the monitor's own API at 02:24:

```
$ curl -s -H "X-Api-Key: ..." http://127.0.0.1:8000/api/v3/checks/ | <count by status>
total=35  up=12  down=8  grace=1  new=14
```

The 8 downs are guards shouting about real findings (crew #80, #81), not dead
instruments — that distinction is the whole point of the board. The 14 "new" rows are
tonight's backups and tomorrow's calendar jobs that have not had their first scheduled
run yet; each turns green on its first ping.

Every one of these jobs also now runs at background priority (`Nice=10`,
`ProcessType=Background`), so the watch never slows the machine you are typing on.

## Alerts reach the phone, 2026-08-24

Every check now alerts Telegram when it flips, through Apprise (bundled in the
healthchecks container, enabled 2026-08-24). Wired and proven with a real flip:

```
$ docker exec estate-healthchecks python manage.py shell -c '...ch.notify(flip)...'
flip: failover-watch down -> up at 2026-08-24 01:55:29
test notify: SENT no error

notification: 2026-08-24 01:56:13 check: failover-watch channel kind: apprise status sent: up error: ''
```

The channel is one Apprise URL (`tgram://`), so swapping Telegram for any other
service is a config edit, not code (LAW 34). The old direct-to-Telegram scripts
still run unchanged as fallback.
