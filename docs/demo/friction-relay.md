# friction-relay — demo

The founder complains to whichever session happens to be open. Every other session never
hears it. This carries his last six hours of complaints into every session that starts.

## What a person sees

```
$ python3 ~/.claude/scripts/friction-relay.py
```

```
[friction-relay] WHAT THE FOUNDER HAS COMPLAINED ABOUT IN THE LAST 6 HOURS.
These were said to whichever session happened to be open. They bind you too.

  - 6m ago (session -chidionyema): "look wtf u talking about"
  - 31m ago (session -chidionyema): "i gave you a fukcinjob get the nnaestro ad he fucking architect opertional wtf has that got to do with fly, we had the billing incident earler, we have a survual fuckiug pla, which should hav been pro"
  - 73m ago (session -chidionyema): "ok sorry i dont see evodence you ae doing aything other tha chattig"
  - 2.4h ago (session -chidionyema): "we nnned this done asap"
  - 2.9h ago (session cuments-code): "all repor shpould be inheriticg , this newly created ones also, if all , ok and you keep ignoring the fucjng elephant in the roon despie nne bring it up nagy tine, wtf is i the claude folders, theses "
  - 3.0h ago (session ema-dev-code): "sorry tform: crew on main, CI green, board serving both numbers. Stack: ~/dev/code/crew/science/law_enforcement.py, reach section. Colima's VM, PID 7650, is holding 26% of memory since 15:55. Not mine"
  ... and 6 more.

  Do not re-ask him something he has already answered above.
```

## What it did

It read every live transcript on the machine, kept the founder's own words (not the
harness talking back), dropped near-duplicates, and wrote the result to a cache that a
SessionStart hook reads in under half a second. The scan itself takes ~16s and runs under
launchd every 10 minutes, never on the session path.

```
$ python3 ~/.claude/scripts/friction-relay.py --selftest
  ok   a tool_result row is not a complaint
  ok   a malformed row does not raise
friction-relay selftest: 9/9 checks passed
```
