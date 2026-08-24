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
