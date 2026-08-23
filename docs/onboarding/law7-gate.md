# Onboarding — the LAW 7 gate

## What this is for

A branch that has not been merged with main does not fail honestly. It fails as
somebody else's bug, naming files and tests the diff never touched, and whoever
is on the branch then spends an hour debugging a fiction that a one-line merge
would have prevented. That is the whole reason LAW 7 exists.

Until now LAW 7 was a sentence agents were expected to remember. The measurement
that prompted this: of the 32 laws, 4 were cited by a live guard and 28 were
prose only. LAW 7 was in the list of laws that are mechanical -- expressible as
a shell command -- and simply were not wired to anything. This wires it.

## What it does

Before a push, for any branch that is not main or master, it fetches
`origin/main` and counts the commits main has that the branch does not. If the
count is above zero it refuses the push and prints the merge command.

It asks the remote, not the local ref. `git rev-list --count HEAD..origin/main`
happily answers zero against an `origin/main` that was last fetched a week ago,
which is exactly the branch this check is about, so it fetches first.

## What it costs

One `git fetch origin main` per push, on branches only. On this machine that is
under a second. Pushing main skips the check entirely and costs nothing.

## Where it lives

`hooks/pre-push` in the claude-guards repository, alongside the LAW 32 check
that was already there. Same file, same pattern, one more reason a push can be
refused. It is active in a repository once that repository points at it:

    git config core.hooksPath scripts/hooks

## How to turn it off

One command, in the repository you want it off in:

    git config --unset core.hooksPath

That disables the LAW 32 feature-docs check as well, because they are the same
hook file. To skip the gate for exactly one push instead, put one honest line in
the commit message:

    Stale-OK: <why>

Use the commit-message line, not `--no-verify`. Both get the push through, but
the first one is reviewable a month later and the second is invisible.

## How to turn it back on

    git config core.hooksPath scripts/hooks

## What goes wrong

**The repository has no main.** The gate fails open. If `git fetch origin main`
returns non-zero, or `origin/main` does not resolve, it passes the push. A guard
that blocks work in a repository it does not understand is worse than no guard.

**You are offline.** The fetch fails, the gate fails open, the push fails anyway
for its own reasons.

**A push is refused and you disagree.** Read the count in the message. If main
really has moved, merging is the answer and it is one line. If you believe the
count is wrong, `git rev-list --count HEAD..origin/main` in that checkout prints
the same number the gate read, and that number is the argument.
