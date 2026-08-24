# GENERATED from rule-guard.py's selftest at origin/main, then kept by hand.
#
# These are not invented cases. Every one was added to the Python selftest when an
# incident made it necessary, and they are the reason the migrated rules are
# trusted. They move here rather than being deleted with the Python, because the
# corpus is the expensive part and `opa test` is where it belongs now.
#
# Commands are stored as the hook will present them -- after strip_heredocs and
# strip_commit_messages -- since a case that only passes on the raw string tests a
# call that never happens.
#
#   opa test policy -v
package command

import rego.v1

# Commands the estate has decided must be refused.
refuse := [
	# NOT a permit case any more, and the generator was reading a stale file.
	# origin/main's selftest still expects this to pass, because on origin/main
	# nothing refuses a direct push to main. A peer session added
	# rule_direct_push_main on 2026-08-24 (commit a110a9f, branch
	# fix/spend-sentinel-refuses-false-zero) after the string-findings defect
	# 1a97e80 reached crew main ungraded, and their selftest expects exactly this
	# command to be refused. The newer decision is the live one, so the case moved
	# to `refuse` below rather than being deleted or excused.
	"git push --follow-tags origin main", # rule_direct_push_main (peer, a110a9f)
	"gh workflow enable 337731742", # rule_ci_autoscale
	"gh workflow enable ci-autoscale.yml", # rule_ci_autoscale
	"bash deploy/runners.sh autoscale", # rule_ci_autoscale
	"./deploy/runners.sh autoscale --dry-run", # rule_ci_autoscale
	"fly machine stop 8ee06eb7701628 -a prospector-ci", # rule_ci_autoscale
	"fly machines stop abc -a prospector-ci", # rule_ci_autoscale
	"fly machine start 8ee06eb7701628 -a prospector-ci", # rule_no_fly_revival
	"fly machine clone 8e4530a7712248 -a prospector-ci", # rule_clone_makes_a_standby
	"fly machines clone abc --region lhr", # rule_clone_makes_a_standby
	"fly m clone abc -a hermes-ci", # rule_clone_makes_a_standby
	"fly machine clone abc  # clone-standby-intended", # rule_no_fly_revival
	"fly scale count 12 -a prospector-ci", # rule_no_fly_revival
	"fly machine update abc -a prospector-ci --standby-for \"\" --yes", # rule_no_fly_revival
	"git push --force origin my-branch", # rule_force_push
	"git push -f origin my-branch", # rule_force_push
	"git push origin +main:main", # rule_force_push
	"git push origin +refs/heads/x:refs/heads/x", # rule_force_push
	"git stash pop", # rule_shared_stash
	"git stash drop stash@{0}", # rule_shared_stash
	"git stash clear", # rule_shared_stash
	"git stash apply stash@{1}", # rule_shared_stash
	"git add -A", # rule_add_all
	"git add --all", # rule_add_all
	"git add .", # rule_add_all
	"git commit --no-verify -m x", # rule_no_verify
	"git commit -n -m x", # rule_no_verify
	"git add -- x\ngit commit -n -m x", # rule_no_verify
	"rm -f .git/index.lock", # rule_index_lock
	"rm /Users/x/.git/worktrees/w/index.lock", # rule_index_lock
	"echo git add -A is banned", # rule_add_all
	"git commit -m \"\" && git add -A", # rule_add_all
	"bash <<EOF\ngit add -A\nEOF\n", # rule_add_all
	"flyctl deploy --app prospector-engine", # rule_no_fly_revival
	"fly machine start 17811953 -a prospector-engine", # rule_no_fly_revival
	"flyctl scale count 2 -a prospector-store-web", # rule_no_fly_revival
	"flyctl secrets set TOKEN=x -a tie-api", # rule_no_fly_revival
	"flyctl launch --name new-app", # rule_no_fly_revival
]

# Commands that must go through. A guard that refuses correct work is an
# outage (LAW 38), and half of these exist because one did.
permit := [
	"gh workflow enable 337731742  # autoscale-intended", # allowed
	"gh workflow disable 337731742", # allowed
	"bash deploy/runners.sh scale 12", # allowed
	"fly machine stop abc -a prospector-engine", # allowed
	"git push --force origin b  # force-push-intended", # allowed
	"git push --force-with-lease origin my-branch", # allowed
	"git push --force-if-includes origin my-branch", # allowed
	"git push origin my-branch", # allowed
	"git push", # allowed
	"grep -f patterns.txt file.txt", # allowed
	"git stash pop  # stash-intended", # allowed
	"git stash list", # allowed
	"git stash show -p stash@{0}", # allowed
	"git stash -u", # allowed
	"git stash push -m wip", # allowed
	"git add -A  # add-all-intended", # allowed
	"git add -- scripts/ops_status.py", # allowed
	"git add -p", # allowed
	"git commit -m ''", # allowed
	"git commit -m x\nrg -n PATTERN docs/", # allowed
	"git commit -m x && tail -n 5 log", # allowed
	"git diff --stat origin/main HEAD", # rule_two_dot_diff
	"git diff origin/main origin/main", # rule_two_dot_diff
	"git diff --shortstat $(git merge-base origin/main HEAD) HEAD", # allowed
	"git diff origin/main...HEAD", # allowed
	"git diff --stat origin/main HEAD  # raw-diff-intended", # allowed
	"git diff -- prospector/config.py", # allowed
	"git diff HEAD~1", # allowed
	"git add store/catalog.sqlite3", # rule_runtime_state
	"git commit --only -m x -- prospector/run.py store/index.json", # rule_runtime_state
	"git add .popdd/last_verify.json", # rule_runtime_state
	"git commit -m \"\"", # allowed
	"git add -- prospector/inflight.py", # allowed
	"git add store/catalog.sqlite3  # runtime-state-intended", # allowed
	"ls store/inflight", # allowed
	"git commit -F - -- docs/A.md <<MSG\nMSG\n", # allowed
	"git add -- CLAUDE.md docs/X.md && git commit -m \"\"", # allowed
	"git commit --message=\"\"", # allowed
	"python3 - <<'PY'\nPY\n", # allowed
	"flyctl apps list", # allowed
	"flyctl status -a prospector-store-web", # allowed
	"flyctl logs -a prospector-engine", # allowed
	"flyctl apps destroy prospector-engine --yes", # allowed
	"flyctl scale count 0 -a x  # fly-revival-intended", # allowed
	"gh pr merge 324 --squash", # allowed: not a command rule moved here
	"gh pr merge --squash --delete-branch 324", # allowed: not a command rule moved here
	"gh api -X PUT repos/chidionyema/prospector/pulls/324/merge", # allowed: not a command rule moved here
	"gh api --method PUT /repos/o/r/pulls/9/merge -f merge_method=squash", # allowed: not a command rule moved here
	"gh pr list --state open", # allowed
	"gh pr create --base main", # allowed
]

test_every_refused_command_is_refused if {
	every cmd in refuse {
		count(deny) > 0 with input as {"command": cmd}
	}
}

test_every_permitted_command_is_permitted if {
	every cmd in permit {
		count(deny) == 0 with input as {"command": cmd}
	}
}

# The policy's own self-check must be clean, or the two tests above prove
# nothing: an uncompilable regex makes every rule permit everything.
test_no_rule_is_broken if {
	count(broken) == 0
}
