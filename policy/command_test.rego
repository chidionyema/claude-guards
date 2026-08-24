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
	# Founder ruling R14, 2026-08-24: paid provisioning, one case per provider.
	"hcloud server create --type cx22 --name k3s-1", # paid_hetzner
	"hcloud volume create --size 10 --name data", # paid_hetzner
	"doctl kubernetes cluster create prod --region lon1", # paid_digitalocean
	"doctl compute droplet create web-1 --size s-1vcpu-1gb", # paid_digitalocean
	"aws eks create-cluster --name prod", # paid_aws
	"aws ec2 run-instances --image-id ami-0abc --count 1", # paid_aws
	"gcloud container clusters create prod --zone europe-west2-a", # paid_gcp
	"gcloud compute instances create node-1 --machine-type e2-medium", # paid_gcp
	"az aks create --name prod -g rg-prod", # paid_azure
	"az vm create --name node-1 -g rg-prod --image Ubuntu2204", # paid_azure
	"linode-cli linodes create --type g6-standard-1", # paid_linode
	"vultr-cli instance create --region lhr", # paid_vultr
	"scw instance server create type=DEV1-S", # paid_scaleway
	"terraform apply -auto-approve", # paid_terraform_apply
	"tofu apply", # paid_terraform_apply
	"pulumi up --yes", # paid_pulumi_up
	# rule_secret_store_dump, migrated from rule-guard.py on 2026-08-24. Every
	# instance is proved BOTH ways: the dumping form here, the names-only form of
	# the SAME tool in `permit` below. A guard only ever seen refusing has never
	# been shown to permit.
	"docker compose -f deploy/compose/docker-compose.yml config", # value dump
	"docker inspect opsconsole-diag2", # value dump
	"docker container inspect x", # value dump
	"gh api repos/chidionyema/prospector/actions/variables", # value dump
	"gh api repos/chidionyema/prospector/actions/variables --jq '.variables[].value'", # value dump
	"gh variable list", # value dump
	"kubectl get secret prospector-engine-env -o yaml", # value dump
	"kubectl get secret prospector-engine-env -o json", # value dump
	"printenv", # value dump
	"printenv | grep PROSPECTOR", # value dump
	"env", # value dump
	"env | sort", # value dump
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
	# R14's other half. The substrate itself, and every read, plan and teardown.
	# Refusing any of these would leave the estate no way to run a cluster at all.
	"k3d cluster create prospector-rehearsal --agents 0 --wait", # allowed: the EUR 0 substrate
	"kind create cluster --name prospector", # allowed: the EUR 0 substrate
	"minikube start --driver=docker", # allowed: the EUR 0 substrate
	"kubectl create namespace prospector", # allowed: costs nothing
	"hcloud server list", # allowed: reading costs nothing
	"hcloud server delete 12345", # allowed: destroying saves money
	"doctl kubernetes cluster list", # allowed: reading costs nothing
	"aws ec2 describe-instances", # allowed: reading costs nothing
	"gcloud container clusters list", # allowed: reading costs nothing
	"az aks list", # allowed: reading costs nothing
	"terraform plan -out=tfplan", # allowed: a plan provisions nothing
	"terraform destroy -auto-approve", # allowed: destroying saves money
	"terraform init", # allowed
	"pulumi preview", # allowed: a preview provisions nothing
	"oci compute instance launch --shape VM.Standard.A1.Flex", # allowed: R14 names Oracle Always Free
	"hcloud server create --type cx22  # founder-approved-spend", # allowed: the escape hatch works
	# The names-only half of every value-dump rule above, plus the two shapes the
	# LAW 45 sweep found that the rule would have refused WRONGLY. Both of those
	# are real lines in this estate and both are correct work.
	"docker compose config --quiet", # allowed: validates, prints nothing
	"docker compose config -q", # allowed
	"docker compose config --services", # allowed: names, not values
	"docker compose up -d", # allowed
	"docker inspect --format '{{.State.Running}}' opsA", # allowed: one field
	"docker inspect x  # value-dump-intended", # allowed: the escape hatch works
	"docker inspect \"$srv\" >/dev/null 2>&1 || fail 'no server'", # allowed: prints nothing
	"docker inspect prospector-store-web \\\n    --format '{{.Id}}'", # allowed: continuation
	"gh api repos/chidionyema/prospector/actions/variables --jq '.variables[].name'", # allowed
	"gh api repos/chidionyema/prospector/actions/runners", # allowed: not a settings store
	"gh variable list --json name", # allowed: names, not values
	"gh secret list", # allowed: gh never prints secret values
	"kubectl describe secret prospector-engine-env", # allowed: names and byte counts
	"kubectl get secrets", # allowed: names only
	"printenv PROSPECTOR_STORE_DIR", # allowed: one name
	"env PROSPECTOR_STORE_DIR=/data/store python3 run.py", # allowed: sets, does not print
	"git diff --stat  # nothing to do with env", # allowed
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
