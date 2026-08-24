# The estate's policy about its own policy code.
#
# WHY THIS EXISTS
# ---------------
# Measured 2026-08-24 on this machine: 108 Python files, 40,425 lines, in
# ~/.claude/scripts. 47 of them are run by something -- a hook in settings.json
# or a job in jobs/jobs.json. The rest are run by nothing. 21 files and 8,678
# lines of that tree are policy: guards, gates and fences, each one its own
# argument parser, its own idea of what a refusal looks like, its own logging.
#
# The founder's words, 2026-08-24: "we need to be deleting pything scripts tbh",
# "too flakey and urelible", and then "policcy as code". OPA 1.19.1 and conftest
# are already installed at /usr/local/bin on this machine, so every one of those
# 21 files was hand-rolled next to an engine that already does the job.
#
# Deleting them is not the hard part. The founder named the hard part himself:
# "this is just chat they wil revet back to old habit soon". A deletion is a
# one-off; the next urgent ticket gets another quick guard script unless
# something refuses it. This file is that refusal.
#
# WHAT IT DOES
# ------------
# A ratchet. `legacy` below is every hand-rolled policy script the estate still
# tolerates, with the line count it is allowed to have. Two things are denied:
#
#   1. a guard/gate/fence .py file that is not in `legacy` -- new hand-rolled
#      policy, which belongs in Rego next to this file instead;
#   2. a file in `legacy` that has grown past its recorded size -- no extending
#      the old Python while the migration is in flight.
#
# Nothing denies shrinking, and nothing denies deleting. Removing a name from
# `legacy` is the migration completing, and it shows up as a deleted line in the
# diff, which is what crew#126 AC6 asks each PR to print.
#
# The numbers are `wc -l` on the file, taken from origin/main at 8c691da.
#
#   conftest test --policy policy inventory.json
package main

import rego.v1

# Every hand-rolled policy script still tolerated, and its ceiling.
#
# This list only ever shrinks. When a script's rules move into Rego, delete the
# script and delete its line here in the same commit.
legacy := {
	"rule-guard.py": 1327,
	"ticket-gate.py": 1098,
	"goal-guard.py": 960,
	"tool-drip-guard.py": 641,
	"close-guard.py": 536,
	"context-guard-hook.py": 499,
	"idle-guard.py": 336,
	"dupe-work-fence.py": 289,
	"peer-loop-fence.py": 285,
	"repeat-guard.py": 283,
	"jargon-guard.py": 269,
	"config-syntax-guard.py": 201,
	"scope-guard.py": 146,
	"laws-link-guard.py": 145,
	"canonical-root-guard.py": 133,
}

deny contains msg if {
	some g in input.guards
	not legacy[g.path]
	not g.symlink
	msg := sprintf(
		"%s is new hand-rolled policy (%d lines). Policy goes in policy/*.rego, which OPA already evaluates. If this genuinely cannot be Rego, say why in the PR and add it to `legacy` in policy/hand_rolled_policy.rego.",
		[g.path, g.lines],
	)
}

deny contains msg if {
	some g in input.guards
	ceiling := legacy[g.path]
	g.lines > ceiling
	msg := sprintf(
		"%s grew from %d to %d lines. The hand-rolled guards are being migrated to Rego, not extended. Move the new rule into policy/*.rego.",
		[g.path, ceiling, g.lines],
	)
}

# A guard nobody runs is the other half of the same problem: 61 of the 108
# Python files on this machine are referenced by no hook and no job, and they
# are never deleted because nobody can tell at a glance that they are dead.
#
# `wired` is supplied by the inventory step, which reads settings/settings.json
# and jobs/jobs.json. A guard that is present, in `legacy`, and wired to nothing
# is dead code.
#
# WARN AND NOT DENY, DELIBERATELY. Two of the files this currently names --
# canonical-root-guard.py (landed 2026-08-23, with its own onboarding doc) and
# tool-drip-guard.py (named as data by reflect.py:594) -- are another session's
# work in progress, not abandoned code. A rule that failed this PR by demanding
# a peer's day-old file be deleted would be a guard refusing correct work, which
# is an outage under LAW 38, and it is not mine to delete alone (LAW 11).
#
# It becomes `deny` when the names it prints are down to zero. That promotion is
# a one-word diff in this file and should be made by whoever clears the last one.
warn contains msg if {
	some g in input.guards
	legacy[g.path]
	not g.path in input.wired
	msg := sprintf(
		"%s is wired to nothing -- no hook in settings/settings.json, no job in jobs/jobs.json. A guard that never runs is not a guard. Delete it, or wire it up.",
		[g.path],
	)
}

# A guard committed as a symlink to an absolute path outside this repository.
#
# Found by this policy's own first CI run, 2026-08-24: the job died because
# `wc -l` could not read idle-guard.py, which is mode 120000 pointing at
# /Users/chidionyema/Documents/code/prospector/scripts/claude_guards/. It
# resolves on one Mac and nowhere else -- not on a runner, not on a second
# machine, not for anyone who clones this repo. The guard is live (it is wired as
# a hook), so its real source is load-bearing and is not in this repository,
# which is LAW 24.
#
# WARN AND NOT DENY. Fixing it means deciding whether this repo or the prospector
# tree owns the file, and leaving two copies to drift is worse than the symlink.
# That is a decision with blast radius in another repository, so it is named here
# on every run and owned by whoever holds that call, not silently swallowed by
# skipping symlinks in the inventory.
warn contains msg if {
	some g in input.guards
	g.symlink
	msg := sprintf(
		"%s is committed as a symlink to %s, outside this repository. It resolves on one Mac and nowhere else; CI checks out a dangling link. Decide which tree owns the file and commit it there (LAW 24).",
		[g.path, g.target],
	)
}
