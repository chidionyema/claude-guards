# friction-relay, running

Every session start, including every compaction, this puts the founder's recent
complaints in front of the session — including the ones he made to a different
session that this one could not otherwise hear.

## What it printed, 2026-08-23 21:0x

    $ python3 ~/.claude/scripts/friction-relay.py

    [friction-relay] WHAT THE FOUNDER HAS COMPLAINED ABOUT IN THE LAST 6 HOURS.
    These were said to whichever session happened to be open. They bind you too.

      - 28m ago (session -chidionyema): "i gave you a fukcinjob get the nnaestro ad he
        fucking architect opertional wtf has that got to do with fly, we had the billing
        incident earler, we have a survual fuckiug pla, which should hav been pro"
      - 71m ago (session -chidionyema): "ok sorry i dont see evodence you ae doing
        aything other tha chattig"
      - 2.3h ago (session -chidionyema): "we nnned this done asap"
      - 2.8h ago (session cuments-code): "all repor shpould be inheriticg , this newly
        created ones also, if all , ok and you keep ignoring the fucjng elephant in the
        roon despie nne bring it up nagy tine, wtf is i the claude folders, theses "
      - 3.0h ago (session ema-dev-code): "sorry tform: crew on main, CI green, board
        serving both numbers. Stack: ~/dev/code/crew/science/law_enforcement.py, reach
        section. Colima's VM, PID 7650, is holding 26% of memory since 15:55. Not mine"
      - 3.2h ago (session ema-dev-code): "wtfwhat are you workng on"
      ... and 6 more.

      Do not re-ask him something he has already answered above.
      If one of these is about work you are doing, it outranks your current step.

Six of twelve are shown because a wall of text gets skimmed. The rest are counted,
not hidden.

## What just happened there

Four different sessions are named in that list — `-chidionyema`, `cuments-code`,
`ema-dev-code`. Before this existed, each of those complaints reached exactly one
session and none of the other five knew about it. That is why he was being annoyed
the same way repeatedly: five sessions could not hear the correction the sixth got.

## It takes 0.1 seconds

    $ time python3 ~/.claude/scripts/friction-relay.py
    0.07s user 0.03s system  0.106 total

The hook reads a cache and never opens a transcript. A separate job rebuilds that
cache every 10 minutes in the background, which is where the real cost sits.

## It checks itself

    $ python3 ~/.claude/scripts/friction-relay.py --selftest
      ok   empty cache injects nothing
      ok   missing key injects nothing
      ok   a complaint is injected
      ok   it carries the age
      ok   it carries the session
      ok   it caps the wall of text
      ok   it says how many it hid
      ok   lexicon is borrowed, not copied
      ok   a tool_result row is not a complaint
      ok   a malformed row does not raise
    friction-relay selftest: 9/9 checks passed
