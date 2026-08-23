# friction-relay

## What it is for

You talk to whichever session happens to be open. Until now, a correction you gave
one session was invisible to the other five, so they carried on annoying you the
same way. This reads what you said to any of them in the last six hours and puts it
in front of every session as it starts — including after a compaction, which is
exactly the moment a session forgets that kind of thing first.

It only reads and reports. It changes nothing and blocks nothing.

## What it costs

Nothing you will notice. The session-start step reads a small cache file and takes
about a tenth of a second. A background job rebuilds that cache every 10 minutes
and takes about 15 seconds, at low priority.

No network calls. No API spend.

## What it reads

Your own transcripts on this machine, under `~/.claude/projects/`. Only your
messages, only the last six hours, only on this laptop. Nothing is sent anywhere —
the output goes into the session that is already reading them.

## Where it lives

    ~/.claude/scripts/friction-relay.py          the program
    ~/.claude/state/friction-relay.json          the cache it reads
    ~/.claude/settings.json                      the SessionStart hook
    ~/Library/LaunchAgents/ai.estate.friction-relay.plist    the 10-minute refresh

## How to turn it off

One command, and it stops immediately:

    launchctl bootout gui/$(id -u)/ai.estate.friction-relay

That stops the refresh. The sessions then read a cache that stops getting newer,
and within six hours it goes quiet on its own because everything in it has aged out.

To stop it completely, including the session-start line, remove the hook:

    python3 - <<'EOF'
    import json, os
    p = os.path.expanduser("~/.claude/settings.json")
    c = json.load(open(p))
    for g in c.get("hooks", {}).get("SessionStart", []):
        g["hooks"] = [h for h in g.get("hooks", []) if "friction-relay" not in h.get("command", "")]
    json.dump(c, open(p, "w"), indent=2)
    EOF

## How to turn it back on

    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.estate.friction-relay.plist

If you removed the hook as well, an agent can re-add it; ask for it by name.

## What goes wrong

**It says nothing.** That is the normal state when you have not complained about
anything in six hours. It is not a failure.

**It shows something stale.** The refresh job has stopped. Check it with
`launchctl list | grep friction` — a dash in the first column means it is not
running right now, which is correct between its 10-minute runs; a non-zero number
in the second column means its last run failed.

**It shows something that was not a complaint.** The word list it uses is borrowed
from the founder board rather than kept as a second copy, so a false positive there
shows up in both places and is fixed in one.

**Anything else.** Every error path exits silently and injects nothing. A hook that
breaks a session start is a hook somebody deletes by lunchtime, so this one fails
open by design — if it is broken you get silence, never a broken session.
