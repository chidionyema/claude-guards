# Demo — the LAW 7 gate

LAW 7 says merge the latest main into a branch before anyone reads it. It has
been a sentence in `~/AGENTS.md` since the law was written. As of this change a
machine refuses the push instead, so nobody has to remember it.

Everything below is real output from a real run against a throwaway repository
with a real remote. The command that produced each block is above it.

## It refuses a branch that main has moved past

A branch is cut from main, then main gains one commit on the remote, then the
branch is pushed without merging.

```
$ echo "refs/heads/feature $SHA refs/heads/feature $ZERO" | python3 hooks/pre-push

push refused: this branch has not been refreshed on main (LAW 7).

  feature is 1 commit(s) behind origin/main

A stale branch does not fail honestly. It fails as somebody else's bug, naming
files and tests your diff never touched, and you then spend an hour debugging a
fiction. Refresh it before anyone reads it:

  git fetch origin main && git merge origin/main --no-edit

Merge, never rebase, and never force push -- the remote moves by itself here, so
a force push destroys work you never saw arrive.

If this genuinely must go stale, put one honest line in the commit message:

  Stale-OK: <why>

rc=1
```

## It passes once you run the command it told you to run

```
$ git merge origin/main --no-edit
$ echo "refs/heads/feature $MERGED refs/heads/feature $ZERO" | python3 hooks/pre-push
rc=0
```

That is the whole loop. The refusal names the fix, the fix is one line, and the
second push goes through.

## It does not fire on main

Pushing main is the integration. A branch cannot be stale against itself, so the
gate skips it and every session pushing straight to main is unaffected.

```
$ echo "refs/heads/main $SHA refs/heads/main $ZERO" | python3 hooks/pre-push
rc=0
```

## It has an escape hatch, and the hatch is honest

A hotfix that must not pick up whatever is on main right now says so in the
commit message. One line, with a reason, in the same shape as the estate's other
fences.

```
$ git commit --allow-empty -m "chore: ship it

Stale-OK: hotfix, main has an unrelated red commit"
$ echo "refs/heads/escaped $SHA refs/heads/escaped $ZERO" | python3 hooks/pre-push
rc=0
```

The hatch exists so the gate does not get bypassed with `--no-verify`. A guard
people route around has stopped nothing, and a reason in the commit message is
reviewable later. A silent `--no-verify` is not.

## Deleting a branch is not a push of anything

```
$ echo "(delete) $ZERO refs/heads/gone $SHA" | python3 hooks/pre-push
rc=0
```

## The full run

Five cases, all as expected: refuse, pass, pass, pass, pass.

```
=== CASE 1: stale feature branch (must REFUSE) ===        rc=1
=== CASE 2: same branch after the merge (must PASS) ===   rc=0
=== CASE 3: pushing main itself (must PASS) ===           rc=0
=== CASE 4: stale branch with Stale-OK (must PASS) ===    rc=0
=== CASE 5: branch deletion (must PASS) ===               rc=0
```
