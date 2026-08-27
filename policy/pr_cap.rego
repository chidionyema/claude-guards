# The PR-queue fences (crew#504 CP5, crew#66), as data instead of code.
#
# pr-cap-guard.py is the adapter: it splits the Bash command, resolves the target
# repository and asks GitHub for its open PRs. Everything it learns is handed here
# as input, and this file makes the two decisions. The hand-rolled ceiling in
# hand_rolled_policy.rego refused the Python growing 143 -> 205 lines for these
# two rules (claude-guards#173, run 33111083509); this is where they belong.
#
# input = {
#   "argv":       ["gh", "pr", "create", "-R", "o/r", ...],   one command, shlex-split
#   "repo":       "owner/name",
#   "prs":        [{number, created_at, head: {ref}, base: {ref}, labels: [{name}]}, ...]
#                 open PRs oldest first, as the REST /pulls endpoint returns them
#   "cap":        20,
#   "hold_label": "hold",
# }
#
# The adapter FAILS OPEN before this file is asked: no gh, no network, unknown
# repo, no opa -- exit 0. A fence on the CI queue must not stop work when GitHub
# is down.
package pr_cap

import rego.v1

is_gh_pr(verb) if {
	input.argv[0] == "gh"
	input.argv[1] == "pr"
	input.argv[2] == verb
}

# crew#538: a PR parked under `hold` pushes nothing and runs nothing; the cap protects
# the CI queue, so a held PR does not count one.
held(pr) if {
	some lab in object.get(pr, "labels", [])
	lab.name == input.hold_label
}

live := [pr | some pr in input.prs; not held(pr)]

oldest := concat(", ", [sprintf("#%v (%s)", [pr.number, substring(pr.created_at, 0, 10)]) |
	some pr in array.slice(live, 0, 3)
])

# 1. `gh pr create` while the repository already has more than `cap` live PRs.
#    2026-08-27: 113 open PRs across seven repos; "we have 24 pull requests open
#    this is crazy". Creating is the only verb that grows the queue; merge, close
#    and review shrink it and stay allowed, so the cap clears itself.
opens_a_slot if is_gh_pr("create")

# crew#538, 2026-08-27: 25 closed PRs were reopened for rescue in one sweep and the queue sat
# at 20/10 for hours; a reopen takes a slot exactly as a create does.
opens_a_slot if is_gh_pr("reopen")

deny contains msg if {
	opens_a_slot
	count(live) > input.cap
	msg := sprintf(
		"%s has %d open PRs (label `%s` not counted), cap is %d (crew#504). Oldest: %s. Merge or close before opening another; merging, closing and reviewing stay allowed.",
		[input.repo, count(live), input.hold_label, input.cap, oldest],
	)
}

# 2. `gh pr merge N --delete-branch` while another open PR is based on N's head.
#    Deleting the base of a stacked PR makes GitHub close that PR (idp#458 was closed
#    by the merge of idp#454, 2026-08-27); restoring the ref, reopening and retargeting
#    cost a slot and an hour. Merge bottom-up without deleting; delete at the top.
deletes_branch if {
	some flag in {"--delete-branch", "-d"}
	flag in input.argv
}

merged_number := [t | some i, t in input.argv; i >= 3; regex.match(`^[0-9]+$`, t)][0]

merged_head := [pr.head.ref | some pr in input.prs; sprintf("%v", [pr.number]) == merged_number][0]

stacked := [sprintf("#%v", [pr.number]) |
	some pr in input.prs
	pr.base.ref == merged_head
	sprintf("%v", [pr.number]) != merged_number
]

deny contains msg if {
	is_gh_pr("merge")
	deletes_branch
	count(stacked) > 0
	msg := sprintf(
		"%s#%s is the base of open PR(s) %s; --delete-branch would make GitHub close them (idp#458, 2026-08-27). Merge without --delete-branch, retarget the stacked PR(s) to main, delete the branch last.",
		[input.repo, merged_number, concat(", ", stacked)],
	)
}
