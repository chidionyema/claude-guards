# Demo — the LAW 22 gate

LAW 22 says a pull request carries a picture of the run passing, not a paste of
it. `pr-evidence.py check` has been able to decide that since it was written.
Nothing called it. This is the caller.

The gate fires only when an OPEN pull request already exists for the branch,
which is the moment the law is about: before review is asked for. The first
push, which creates the branch, has nothing to attach evidence to yet.

## Real runs

Branch with no pull request. The gate stays out of the way.

```
$ echo "refs/heads/feature $SHA refs/heads/feature $ZERO" | python3 hooks/pre-push
rc=0
```

Commit message carrying the escape hatch.

```
$ git commit --allow-empty -m "chore: waived

No-Evidence: infrastructure change with no runnable surface"
$ echo "refs/heads/waived $SHA refs/heads/waived $ZERO" | python3 hooks/pre-push
rc=0
```

The decision itself, driven against each answer `gh` and `pr-evidence.py` can
give. A live pull request is the only other way to reach these branches, so
they are exercised directly rather than described.

```
open PR, no evidence        -> '  PR #41: #41 has no verification evidence. LAW 22: attach a screenshot'
open PR, evidence attached  -> None
gh unavailable / no PR      -> None
pushing main                -> None
```

`None` means the gate passes the push. A string means it refuses and prints it.

## What a refusal looks like

```
push refused: this pull request has no picture of the run (LAW 22).

  PR #41: #41 has no verification evidence. LAW 22: attach a screenshot

Pasted output is typed by hand in seconds and reads the same whether the run
happened or not. Attach a photograph of it instead:

  pr-evidence.py shot - --out /tmp/p.png --title "pytest -q" < run.log
  pr-evidence.py attach --pr <n> /tmp/p.png --caption "what it proves"
```
