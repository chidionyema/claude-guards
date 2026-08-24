# Repository secrets — what it looks like when it runs

On 2026-08-23 two repositories were about to be made public. The scan that checked them for
credentials was written by hand in a scratchpad, run once, and thrown away. The founder's reply is
the reason this file exists:

> "why isnt this automated already, thats why we are always firefighting"

A check that exists only when somebody remembers to write it is not a check, and the moment it is
needed most is the moment nobody has time to write it.

## The gate, live

```
$ python3 repo_secrets.py --diff origin/main...HEAD
. origin/main...HEAD: 0 blocking, 0 to verify by hand
```

That runs in pre-push. It reads what the push adds and nothing else, so it is fast enough to sit in
front of every push without anyone wanting to bypass it.

## The control

```
$ python3 repo_secrets.py --selftest
repo_secrets selftest PASSED
```

## Two entry points, because the risk has two shapes

`--diff` is what this push adds. Fast, in pre-push, refuses the push.

`--history` is what the repository has ever held. Slower, on a schedule over the public
repositories, because a key in an old commit is readable no matter what the tip says. Rotating a key
and force-pushing over it does not remove it from a fork or from anyone's clone.

## What blocks and what only reports

This is the difference between a gate people keep and a gate people bypass with `--no-verify`.

Every pattern under STRONG is anchored on a provider's own prefix and its real length. A match is a
key or it is a test fixture, and there is no third option. Those block.

The one pattern that reads `secret = <something long>` lives under WEAK and never blocks. On its
first real run it produced three hits in survival-stack and all three were false, every one an
environment variable name rather than a value. A gate that fires on three false positives in its
first hour is a gate that gets switched off in its second.

## What it does not replace

`secret-scrub.py` keeps keys out of the local files that collect them by accident: `history.jsonl`,
`.zsh_history`, checkpoint notes. It runs on Stop and it only ever looks at those files. Nothing
looked at a repository before this, which is how the hand-written scratchpad scan came to be the
only thing standing between two repositories and a public URL.
