# pr-cap-guard: demo

What you see when a session tries to open a PR against a repo that already has more than 10 open (crew#504):

```
$ gh pr create -R chidionyema/idp --title "feat: x" --body-file /abs/body.md
BLOCKED by pr-cap-guard: chidionyema/idp has 14 open PRs, cap is 10 (crew#504). Oldest: #353 (2026-08-25), #358 (2026-08-25), #379 (2026-08-26). Merge or close before opening another; merging, closing and reviewing stay allowed.
```

What it just did: asked GitHub for the open PRs of the target repo (the `-R` flag, else the checkout's `origin`), counted them, and refused the one command that grows the queue. Nothing was created. `gh pr merge`, `gh pr close`, `gh pr review` and every other command pass untouched, so the queue can only fall until the guard lets creation through again.

Self-check, both ways:

```
$ python3 ~/.claude/scripts/pr-cap-guard.py --selftest
PASS 11 open refuses: want 2 got 2
PASS 10 open allows: want 0 got 0
PASS gh unavailable fails open: want 0 got 0
PASS merge stays allowed at 11: want 0 got 0
PASS close stays allowed at 11: want 0 got 0
PASS unknown repo fails open: want 0 got 0
```
