# Onboarding — the LAW 22 gate

## What this is for

An agent claiming a test suite is green costs nothing and reads identically
whether the run happened or not. That is where every false green on this estate
has come from. A screenshot is a photograph of something that existed. It is not
proof against a determined forger and is not meant to be; it raises the cost of
the claim from zero to something.

`pr-evidence.py check --pr N` could already decide whether a pull request
carries evidence. Nothing called it, so LAW 22 was a sentence. This calls it.

## What it does

Before a push from a branch, if an OPEN pull request exists for that branch, it
runs the evidence check and refuses the push when the pull request carries none.
It skips main and master, and it skips the branch's first push, when there is no
pull request to attach anything to.

## What it costs

One `gh pr view` per push from a branch, about a second, and only when the push
is not to main. No cost at all on main.

## Where it lives

`hooks/pre-push` in the claude-guards repository, next to the LAW 7 and LAW 32
checks. Active in a repository once that repository binds the hooks path:

    git config core.hooksPath scripts/hooks

## How to turn it off

    git config --unset core.hooksPath

That drops the LAW 7 and LAW 32 checks too, because they share the file. To skip
it for one push, put an honest line in the commit message:

    No-Evidence: <why>

Use that rather than `--no-verify`. Both get the push through; only one is
reviewable a month later.

## How to turn it back on

    git config core.hooksPath scripts/hooks

## What goes wrong

**It fails open on every unknown.** No `gh` on the machine, `gh` not
authenticated, no pull request, a network failure, the checker missing: the push
goes through. A gate that stops the estate because a network call failed has
made a screenshot more important than the work.

**A pull request that genuinely has no runnable surface.** Use the hatch. A
config change with nothing to photograph is the case it exists for.
