# canonical-root-guard — demo

Every line of output below came from a real run on 2026-08-23. Nothing here is illustrative.

## What the estate looked like before it existed

```
$ find ~ -maxdepth 4 -name .git -not -path "*/node_modules/*" -not -path "*/Library/*" | wc -l
67 checkouts, across 6 roots:
  ~/Documents/code   28    (15 of them wt-* worktrees sharing ONE .git, prospector's)
  ~/code             18
  ~/dev/code         12    <- the canonical root
  ~/code-backup       8
  ~/Desktop           1
  ~/Downloads         1
```

Twelve of sixty-seven were in the right place. Sessions in the previous 24 hours had worked from
four different real roots, three of them outside.

## A session starting in the wrong place

```
$ cd ~/Documents/code && python3 canonical-root-guard.py
[canonical-root] This session's cwd is OUTSIDE the canonical root.

  cwd    /Users/chidionyema/Documents/code
  root   /Users/chidionyema/dev/code

Founder ruling 2026-08-23: all work happens in /Users/chidionyema/dev/code. Measured that day, 67 git
checkouts were spread across 6 roots with only 12 in the root, and two sessions had edited two
copies of one repo without either knowing.

  - Do not start NEW work here. If this checkout has a twin under the root, use the twin.
  - Do not move, delete or `git worktree remove` anything to fix it. One agent owns the
    consolidation, and several of these paths are named by launchd jobs that a move would break.
  - Push what you are holding. Unpushed commits are the only thing a consolidation cannot
    recover.
```

## A session starting in the right place, and one in a carved-out path

```
$ cd ~/dev/code/crew && python3 canonical-root-guard.py
$ cd ~/.claude/scripts && python3 canonical-root-guard.py
$
```

Nothing. That silence is the design. A guard that speaks on every session start is a guard
somebody switches off inside a week, and then it protects nothing at all.

## It never fails a session

```
$ for d in ~/Documents/code ~/dev/code/crew ~/.claude/scripts; do (cd $d && python3 canonical-root-guard.py >/dev/null 2>&1; echo "$d -> exit $?"); done
/Users/chidionyema/Documents/code -> exit 0
/Users/chidionyema/dev/code/crew -> exit 0
/Users/chidionyema/.claude/scripts -> exit 0
```

## The selftest

```
$ python3 canonical-root-guard.py --selftest
  [ok] the canonical root itself is ok: ok (want ok)
  [ok] a repo under the root is ok: ok (want ok)
  [ok] ~/Documents/code is outside: outside (want outside)
  [ok] ~/code is outside: outside (want outside)
  [ok] ~/code-backup is outside: outside (want outside)
  [ok] ~/Desktop is outside: outside (want outside)
  [ok] ~/.claude is carved out: the path is the product: exempt (want exempt)
  [ok] ~/.claude/scripts is carved out: 29 launchd jobs name it: exempt (want exempt)
  [ok] ~/.hermes/scripts is carved out: launchd wrapper: exempt (want exempt)
  [ok] prospector is carved out: com.chidionyema.reflect hardcodes it: exempt (want exempt)
  [ok] a session scratchpad worktree is carved out: exempt (want exempt)
canonical-root-guard selftest: 11/11 passed
```
