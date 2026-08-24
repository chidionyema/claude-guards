# Wrapping jobs for dead-man monitoring — what it looks like when it runs

`launchctl list` reports the last exit code. A job whose program no longer exists shows 0 with empty
stderr and reads as healthy forever. That is the incident behind "exit 0 is not proof of work": 43
fake successes hid a dead dashboard.

A dead-man check fixes the class. The job pings a receiver when it starts and again with its exit
code. Silence is the alarm, so a job that never runs is as loud as a job that fails.

## What is covered right now

```
$ bash estate/measure-wrap-coverage.sh
BARE     com.founder.estatewatch
BARE     ai.hermes.runaway-reaper
BARE     com.prospector.scheduler
BARE     ai.estate.drills
BARE     com.founder.estatepush
BARE     com.founder.estate-awake

total=47  direct=15  indirect=1  bare=31
```

That number comes from `launchctl list`, not from this tool's opinion of what it did. The two are
different and the difference is the point.

## The migration, in report mode

```
$ python3 estate/wrap-jobs.py
  com.prospector.offsite-backup          already pings as prospector-offsite-backup
  com.prospector.restore-drill           already pings as restore-drill

== always-on (8) ==
  ai.architect.gateway                   KeepAlive: meant never to exit, so an exit ping says nothing
  ai.estate.consultd                     KeepAlive: meant never to exit, so an exit ping says nothing
  ai.estate.deepseek-bridge              KeepAlive: meant never to exit, so an exit ping says nothing
  ai.estate.kimi-bridge                  KeepAlive: meant never to exit, so an exit ping says nothing
  com.chidionyema.maestro                KeepAlive: meant never to exit, so an exit ping says nothing
  com.founder.boardserve                 KeepAlive: meant never to exit, so an exit ping says nothing
  com.founder.estate-awake               KeepAlive: meant never to exit, so an exit ping says nothing
  com.prospector.scheduler               KeepAlive: meant never to exit, so an exit ping says nothing

== no-plist (4) ==
  com.cisco.anyconnect.gui               no plist at ~/Library/LaunchAgents/com.cisco.anyconnect.gui.plist
  com.cisco.anyconnect.notification      no plist at ~/Library/LaunchAgents/com.cisco.anyconnect.notification.plist
  com.ollama.ollama                      no plist at ~/Library/LaunchAgents/com.ollama.ollama.plist
  com.openssh.ssh-agent                  no plist at ~/Library/LaunchAgents/com.openssh.ssh-agent.plist

total=51  wrapped=15  wrappable=24  refused=12

Nothing was written. Pass --fix LABEL [LABEL ...] to wrap named jobs.
```

Report mode is the default. `--fix` is the only thing that writes, and it takes labels rather than
sweeping, so a bad transform lands on one job and not on forty.

## Every refusal is printed, and none of them is a gap

The eight always-on jobs have `KeepAlive`. They are meant never to exit, so an exit ping carries no
information and a start ping would fire once at boot. Wrapping them would produce a monitor that is
green because nothing ever pings it.

The four with no plist are Apple's and vendors' own, loaded from outside this user's LaunchAgents
directory. There is no file to edit.

A refusal you can read is worth more than a number you cannot audit. Twelve refused, twelve reasons
on screen.

## The transform

```
["/usr/bin/python3", "tick.py"]
  -> ["<hc-wrap.sh>", "<slug>", "/usr/bin/python3", "tick.py"]
```

`hc-wrap.sh` pings `<slug>/start`, runs the job unchanged, and pings `<slug>/<exit code>`. It never
changes the job's exit status and it never fails the job when the receiver is down. A monitoring
wrapper that can take down the thing it monitors is worse than no monitoring.
