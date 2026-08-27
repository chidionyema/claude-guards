# pr-cap-guard: demo

What you see when a session tries to open a PR against a repo that already has more than 20 open (crew#504; founder 2026-08-27 raised it from 10: "increse the slot to 20"):

```
$ gh pr create -R chidionyema/idp --title "feat: x" --body-file /abs/body.md
BLOCKED by pr-cap-guard: chidionyema/idp has 21 open PRs (label `hold` not counted), cap is 20 (crew#504). Oldest: #11 (2026-08-24), #27 (2026-08-24), #29 (2026-08-24). Merge or close before opening another; merging, closing and reviewing stay allowed.
```

What it just did: asked GitHub for the open PRs of the target repo (the `-R` flag, else the checkout's `origin`), counted them, and refused the one command that grows the queue. Nothing was created. `gh pr merge`, `gh pr close`, `gh pr review` and every other command pass untouched, so the queue can only fall until the guard lets creation through again.

Self-check, both ways:

```
$ python3 ~/.claude/scripts/pr-cap-guard.py --selftest
PASS 11 open refuses: want 2 got 2
PASS 20 open allows: want 0 got 0
PASS gh unavailable fails open: want 0 got 0
PASS merge stays allowed at 11: want 0 got 0
PASS close stays allowed at 11: want 0 got 0
PASS unknown repo fails open: want 0 got 0
```

## Second fence: stacked PRs (crew#66, 2026-08-27)

    gh pr merge 454 -R chidionyema/idp --squash --delete-branch
    BLOCKED by pr-cap-guard: chidionyema/idp#454 is the base of open PR(s) #458; --delete-branch would make GitHub close them ...

Merging idp#454 with `--delete-branch` closed idp#458, which was based on it; restoring the ref, reopening and retargeting cost a cap slot and an hour. Merge the bottom without deleting, retarget the stacked PR to main, delete the branch at the top.
