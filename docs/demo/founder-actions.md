# Demo: what is waiting on the founder

Every item only the founder can authorise, in one place, closing itself when the world changes.
Below is a real run, not an illustration.

## The register, right now

```
$ python3 ~/.claude/scripts/founder_actions.py
2 things only the founder can clear

  [open] Authorise the encrypted secret store to be created, either by pasting one line into a
         live session or by granting an agent the permission once.
      only him because: Every agent route into it is refused by the Claude Code auto mode
                        classifier. Four different implementations were tried on 2026-08-23 and
                        all four were refused with the same reason.
      it releases:      The last disaster recovery hole. Today a fresh box can restore all six
                        data sources from R2 and cannot start a single service.
      tracked at:       https://github.com/chidionyema/prospector/issues/672
      closes when:      test -f $HOME/Documents/code/prospector-live/deploy/secrets.env.age
                        -> exit 1

  [unverifiable] Put the age private key somewhere that is not this laptop, such as a password
                 manager.
      only him because: It is a physical act with a secret value, and no agent may ever copy
                        that value anywhere it can be read again.
      it releases:      Without it the encrypted store is useless after a laptop loss, which is
                        the exact disaster the store exists to survive.
      closes when:      no command can establish this, so it stays visible until retired
```

Exit code is 1 while anything is outstanding and 0 when nothing is, so a scheduler can act on it.

## The same two items on the estate board

The point is that he never runs the command above. The rows arrive on the page he already has
open at http://127.0.0.1:8787, under access and change control:

```
$ python3 -c "import estate_audit as A; [print('%-9s %-45s %s' % (r['severity'], r['title'], r['value'])) for r in A.c_founder_actions()]"
warn      Founder must clear: secret-store-exists       WAITING
unknown   Founder must clear: age-key-escrowed-off-this-laptop CANNOT TELL
```

`WAITING` means a command checked and the thing has not happened yet. `CANNOT TELL` means no
command can settle it, so it is reported as unknown and never as a pass.

## It closes itself

The first item's `done_when` is `test -f .../deploy/secrets.env.age`. The moment that file
exists the item grades done, and the next sweep drops it out of the register with nobody
remembering to close it.

```
$ python3 ~/.claude/scripts/founder_actions.py --sweep
OPEN      secret-store-exists        test -f $HOME/.../secrets.env.age -> exit 1
UNVERIFIABLE age-key-escrowed-off-this-laptop  no command can establish this
```

## The tests that hold it up

```
$ python3 ~/.claude/scripts/founder_actions.py --selftest
selftest: PASS
```

Three properties rather than a pile of examples: a `done_when` exiting 0 reads done, one exiting
non-zero reads open, and a missing one can never read done. Plus two on the register itself, that
re-adding an id updates instead of duplicating, and that a sweep retires the done and keeps the
unverifiable.
