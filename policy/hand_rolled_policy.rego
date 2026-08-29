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
# The numbers are `wc -l` on the file, taken from origin/main at 8c691da,
# except rule-guard.py: nine of its rules are Rego now, so its ceiling is the
# post-cutover count. A ceiling only ever falls.
#
#   conftest test --policy policy inventory.json
package main

import rego.v1

# Every hand-rolled policy script still tolerated, and its ceiling.
#
# This list only ever shrinks. When a script's rules move into Rego, delete the
# script and delete its line here in the same commit.
legacy := {
	# 1114 -> 1120 on 2026-08-24, and this is the first time this list has gone up.
	# The ceiling counts lines, so it cannot tell a new rule from a bug fix. What was
	# fixed: `gh pr merge 2 --repo owner/name` was graded against a different repository,
	# reporting python=failure dotnet=failure from prospector on a repository that has no
	# workflows at all -- and on a refusal path marked `no override`, so a correct command
	# could not be run. rules_count is unchanged: `grep -c '^def rule_'` is the same before
	# and after, because no rule was added. Six of the six lines are the flag pattern, its
	# two-line comment, and passing the name through to gh.
	# 1120 -> 1174 on 2026-08-26 (session 4e5b5e8f). No refusal was added: rules_count is
	# still 6 and the refusal is command.rego's orphaned_worktree rule. The lines are the
	# state Rego cannot gather -- orphan_state() stats the targeted `.wt-*` dir and names
	# the checkout git would act on -- plus its both-ways selftest. This is the shape the
	# header prescribes for a live question: adapter gathers, Rego decides.
	# 1174 -> 1198 on 2026-08-26 (session 78caaa17, crew#51). No refusal was added: rules_count
	# is still 6. strip_echo_payloads drops what echo/printf prints before the command reaches
	# Rego, next to heredoc bodies and -m messages; Rego judges the command it is handed, so
	# the stripping is the adapter's job. Both-ways cases are in the selftest.
	# 1282 -> 1310 on 2026-08-27 (session 78caaa17, crew#423 row 25, claude-guards#137). No refusal
	# was added: rules_count is still 6 and the refusal is command.rego's LAW 25 rule (a switch
	# command while checkpoints/LATEST.md is more than 30 min old). The lines are the state Rego
	# cannot gather: checkpoint_age_s() stats LATEST.md next to the transcript, walks up from a
	# subagents/ transcript, and hands None (BLIND) when there is no file. Adapter gathers, Rego decides.
	# 1353 -> 1452 on 2026-08-29 (session 14ed6c8b, crew#488). No refusal was added: rules_count is
	# still 7 (`grep -c '^def rule_'` before and after), and the new dimension lives inside
	# rule_merge_red_pr -- one of the four this file's header names as unable to move, because it
	# asks gh a live question. It asks two more: `gh api {repo}/rulesets` for the required contexts,
	# and the PR's own check names, because the decision is "is there a check GitHub will not wait
	# for" and neither set is in the command. Rego cannot shell out; a pattern-only version would be
	# a blanket ban on --auto, which is LAW 38 in a repository whose required set is complete.
	# WHY: idp#675 was merged by --auto at 00:35:33Z with portability-drill run 33223840305 still
	# going; it concluded FAILURE and main's gate was out ~30 min. Adapter gathers, Rego decides is
	# the shape this becomes when a runner can hand OPA the check names and the required set.
	"rule-guard.py": 1452,
	# crew#407 (claude-guards#118): the credential shapes use lookarounds ((?!...), (?<!...)) that
	# RE2, and so OPA, cannot run, and the one definition is estate_alert.credential_shape, shared
	# with the Telegram senders (#113). The hook is the adapter for two events (Stop reply text,
	# PreToolUse gh writes); the decision is one function call. Ceiling only ever falls.
	"credential-guard.py": 118, # crew#332: foreign_changes() asks git status and stats files; the refusal is Rego
	# 1098 -> 1107 on 2026-08-26 (crew#323, claude-guards#92). No refusal was added: the gate
	# graded a compaction summary ("This session is being continued from a previous
	# conversation", "Caveat:", "Stop hook") as founder words and demanded a ticket for it.
	# The nine lines are the NOT_FOUNDER_WORDS prefix list and the startswith() that reads it.
	# It is a transcript-shape rule, and no runner feeds transcripts to OPA yet; same follow-up
	# and same exit as dod-guard below.
	# 1107 -> 1109 on 2026-08-27 (claude-guards#127). No refusal was added: one more entry in the
	# same NOT_FOUNDER_WORDS list (a monitor's liveness probe, "Answer with one word and nothing
	# else", filed four times as crew#334-#337). Same transcript-shape rule, same missing runner,
	# same exit: the list moves to Rego with the Stop/transcript runner named on crew#281.
	"ticket-gate.py": 1109,
	"goal-guard.py": 960,
	"tool-drip-guard.py": 641,
	"close-guard.py": 536,
	"context-guard-hook.py": 499,
	"idle-guard.py": 336,
	"dupe-work-fence.py": 289,
	# crew#504: the decision is an authenticated GitHub call (open PR count) per
	# invocation; Rego would need the gh token in the hook input to http.send it.
	"pr-cap-guard.py": 143,
	"peer-loop-fence.py": 285,
	"repeat-guard.py": 283,
	"jargon-guard.py": 269,
	"config-syntax-guard.py": 201,
	"scope-guard.py": 146,
	"laws-link-guard.py": 145,
	"canonical-root-guard.py": 133,
	# 192 -> 202 on 2026-08-26 (crew#281 CP2, claude-guards#65): STAGED: is a fifth reply word and
	# must carry the founder's go/hold sentence and a minute count. It is a Stop-hook rule over
	# the reply text; opa-hook.py runs only on PreToolUse (Artifact) and no Stop runner feeds a
	# transcript to OPA yet, so the rule cannot be Rego today. Follow-up on crew#281: a Stop
	# runner, then dod-guard and blocker-guard move to policy/reply.rego and leave this list.
	"dod-guard.py": 202,
	# Added 2026-08-26 at 94 lines, the first time it is committed: settings.json has run it
	# untracked since 2026-08-25 (LAW 24). Same reason as dod-guard: a Stop rule over the reply
	# and the Telegram ledger, no OPA Stop runner exists. Same follow-up, same exit.
	"blocker-guard.py": 94,
	# 176 -> 212 on 2026-08-26 (crew#331, #99). The rule itself (a handoff on a lane another
	# live session holds is refused unless the holder is named on the OVERLAP line) went into
	# policy/feed.rego with three tests. The 36 Python lines are the data OPA cannot read for
	# itself: holders() walks feed.md for the sessions inside the 2h hold and hands them in as
	# input.holders; sweep counts the last 24h a lane-hold rule would have refused (LAW 45
	# step 4, printed 145 on the live feed); two selftest cases prove the guard both ways.
	# 212 -> 240 on 2026-08-27 (crew#403 CP6, claude-guards#152). next_answer() injects the bar
	# and red rows of idp docs/NEXT.md with its URL when the founder asks about status,
	# capabilities, progress or when. It is content, not a decision: OPA cannot read the page
	# or print it into the prompt. The prompt match (STATUS_RE) is the only rule, and it has
	# no refusal to migrate; three incident tests prove it both ways.
	"feed-guard.py": 270,
	# vendor-lock-guard (crew#273, claude-guards#63): scans PROSE -- markdown, .feature and
	# the last assistant message -- for a vendor name in the same sentence as a word that
	# makes it mandatory. conftest has no parser for markdown or free text, so this rule
	# cannot be Rego; recorded at its landing size. Only ever falls.
	"vendor-lock-guard.py": 196,
	# cg#183: shells out to git (merge-base, diff --stat, rev-list, symbolic-ref) to measure a
	# merge target's distance before the merge runs; conftest has no git, so the measurement
	# cannot be Rego. Tracked for the first time at its landing size (it ran untracked from
	# 2026-08-27 13:00). Only ever falls.
	"merge-target-divergence-guard.py": 159,
	# cg#208 (crew#603 CP2): not a refusal but an action -- git fetch, merge --ff-only or
	# checkout --detach at SessionStart, and the collision set (incoming ∩ dirty) that stops
	# it comes from git diff/status. conftest has no git and Rego cannot move a checkout.
	# Tracked at its landing size. Only ever falls.
	"sync-guard.py": 98,
}

# How many command refusals each guard still implements in Python. Same direction
# as `legacy`: it only ever falls.
#
# The line ceiling alone does not catch the reversion the founder named. A session
# can add a tenth rule function and delete a comment block to stay under it, and
# the diff reads as a shrink. This counts the thing itself. The six left in
# rule-guard.py are the ones that shell out to git or gh to ask about the live
# tree, which Rego cannot do. The seventh (rule_self_symlink, 2026-08-28) asks the
# filesystem whether `ln -s` target and link resolve to the same path, or whether -f
# would unlink a regular file: a stat, not a regex.
rule_ceiling := {"rule-guard.py": 7}

deny contains msg if {
	some g in input.guards
	ceiling := rule_ceiling[g.path]
	g.rules > ceiling
	msg := sprintf(
		"%s implements %d command refusals in Python, up from %d. A refusal is an entry in policy/command.rego with its must_match and must_not_match examples -- `make guard NAME=...` scaffolds one. If it genuinely has to ask git or gh a live question, say so in the PR and raise the number in `rule_ceiling`.",
		[g.path, g.rules, ceiling],
	)
}

# policy/ holds Rego. A Python file under it is the old habit finding a new home,
# and that is not hypothetical: policy/differential.py lived there for the length
# of one migration and had to be deleted by hand when it was done.
deny contains msg if {
	some f in input.policy_dir_py
	msg := sprintf(
		"%s is Python under policy/. That directory is Rego, which OPA already evaluates. Put the rule in policy/command.rego and its cases in policy/command_test.rego.",
		[f],
	)
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

# A hook wired to a file that does not exist.
#
# THE MISTAKE, 2026-08-24, mine. I repointed the Artifact PreToolUse hook at
# opa-hook.py in the live ~/.claude/settings.json while opa-hook.py existed only
# on a branch. ~/.claude/scripts IS this repository's checkout, so the file was
# not there. Every Artifact call then exited 2 -- publish AND read -- because
# python3 exits 2 on "can't open file". A guard that refuses correct work is an
# outage (LAW 38), and this one refused everything, silently, until a selftest
# happened to print the errno. Measured: publish -> 2, read -> 2, want 2 and 0.
#
# THE CLASS: settings.json names a hook command whose file is not in the tree
# that CI checks out. Wiring lands in one commit and the file in another, or in
# no commit at all. Nothing checked the two agreed.
#
# WIDTH. Every hook in settings/settings.json, not the one I touched. It is
# deliberately NOT extended to jobs/jobs.json: those name absolute paths in other
# repositories -- launchd_receipt.py lives in the hermes tree, backup_store.py and
# five others in prospector-main -- and denying them here would fail this repo for
# another repo's layout. Measured on this tree: 7 such names, 0 of them hooks.
#
# DENY AND NOT WARN. Unlike the two warns above, there is no judgement call and no
# other repository involved: the file is either in `git ls-files` or the hook
# cannot run. Sweep at the time of writing: 20 hook names, 20 tracked, 0 failures,
# so this passes today and would have refused my commit.
deny contains msg if {
	some name in input.hooks_wired
	not name in input.tracked_py
	msg := sprintf(
		"settings/settings.json wires a hook to %s, which is not a tracked file in this repository. ~/.claude/scripts IS this checkout, so python3 exits 2 on every matching tool call -- the hook refuses reads as well as writes. Commit the file in the same change as the wiring, or revert the wiring (LAW 38).",
		[name],
	)
}
