# Both directions for every rule in pr_cap.rego: what it must refuse, what it must permit.
package pr_cap_test

import rego.v1

import data.pr_cap

fake(n) := [{"number": i, "created_at": sprintf("2026-08-%02dT00:00:00Z", [i])} | some i in numbers.range(1, n)]

base := {"repo": "o/r", "cap": 10, "hold_label": "hold"}

create := ["gh", "pr", "create", "-R", "o/r", "--title", "t"]

stack := [
	{"number": 454, "created_at": "2026-08-27T00:00:00Z", "head": {"ref": "cp1"}, "base": {"ref": "main"}},
	{"number": 458, "created_at": "2026-08-27T00:00:00Z", "head": {"ref": "cp2"}, "base": {"ref": "cp1"}},
]

test_eleven_open_refuses_and_names_the_oldest if {
	d := pr_cap.deny with input as object.union(base, {"argv": create, "prs": fake(11)})
	count(d) == 1
	some m in d
	contains(m, "o/r has 11 open PRs")
	contains(m, "Oldest: #1 (2026-08-01), #2 (2026-08-02), #3 (2026-08-03)")
}

test_ten_open_permits if {
	count(pr_cap.deny) == 0 with input as object.union(base, {"argv": create, "prs": fake(10)})
}

test_held_prs_do_not_count if {
	prs := array.concat([{"number": 1, "created_at": "x", "labels": [{"name": "hold"}]}], fake(10))
	count(pr_cap.deny) == 0 with input as object.union(base, {"argv": create, "prs": prs})
}

test_merge_and_close_stay_allowed_at_eleven if {
	count(pr_cap.deny) == 0 with input as object.union(base, {"argv": ["gh", "pr", "merge", "5", "-R", "o/r", "--squash"], "prs": fake(11)})
	count(pr_cap.deny) == 0 with input as object.union(base, {"argv": ["gh", "pr", "close", "5", "-R", "o/r"], "prs": fake(11)})
}

test_delete_branch_under_a_stacked_pr_refuses if {
	d := pr_cap.deny with input as object.union(base, {"argv": ["gh", "pr", "merge", "454", "-R", "o/r", "--squash", "--delete-branch"], "prs": stack})
	count(d) == 1
	some m in d
	contains(m, "o/r#454 is the base of open PR(s) #458")
}

test_short_d_flag_is_the_same_refusal if {
	count(pr_cap.deny) == 1 with input as object.union(base, {"argv": ["gh", "pr", "merge", "454", "-d"], "prs": stack})
}

test_merge_without_delete_permits if {
	count(pr_cap.deny) == 0 with input as object.union(base, {"argv": ["gh", "pr", "merge", "454", "-R", "o/r", "--squash"], "prs": stack})
}

test_top_of_the_stack_may_delete if {
	count(pr_cap.deny) == 0 with input as object.union(base, {"argv": ["gh", "pr", "merge", "458", "--delete-branch"], "prs": stack})
}

test_unknown_pr_number_permits if {
	count(pr_cap.deny) == 0 with input as object.union(base, {"argv": ["gh", "pr", "merge", "999", "--delete-branch"], "prs": stack})
}
