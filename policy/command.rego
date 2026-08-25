# The refusals that only need to read the command, as data instead of code.
#
# WHAT MOVED HERE AND WHY
# -----------------------
# rule-guard.py is a PreToolUse hook: 1,327 lines of Python that fires on every
# Bash call in every session on this machine. Sixteen refusals live in it, and
# fourteen of them have the same shape -- a compiled regex, an override marker,
# and a message. That shape is a table. It was written as code because there was
# nothing to write it as data for; OPA 1.19.1 has been installed at
# /usr/local/bin the whole time.
#
# Founder, 2026-08-24: "we need to be deleting pything scripts tbh", then
# "policcy as code", then "this is just chat they wil revet back to old habit
# soon".
#
# Measured on this machine, 2026-08-24, eight runs each:
#   opa eval on this policy   0.05 0.04 0.04 0.04 0.04 0.04 0.04 0.04 s
#   rule-guard.py per call    0.14 0.17 0.16 0.17 0.14 0.22 0.41 0.34 s
# The engine is faster than the Python it replaces, on the hook that fires most
# often on this estate. There is no latency argument for keeping the Python.
#
# WHAT DID NOT MOVE
# -----------------
# Four refusals ask git or gh a question before deciding -- rule_two_dot_diff
# (git rev-parse), rule_pr_size (git diff), rule_merge_red_pr (gh pr checks),
# rule_commit_in_shared_checkout (git rev-parse). Rego cannot shell out, by
# design, so those stay in Python until the adapter gathers that state and
# passes it in as input. They are not listed here and rule-guard.py keeps them.
#
# THE TRAP THIS POLICY SETS FOR ITSELF
# ------------------------------------
# OPA's regex engine is Go's RE2, which has no lookahead. Two of these rules
# used it: `--force(?!-with-lease|-if-includes)` and `main\b(?![-/])`. Both are
# rewritten below with RE2-expressible equivalents, and `differential.py` proves
# the rewrites agree with the Python originals on every case.
#
# The dangerous part is not that RE2 rejects the pattern. It is HOW it rejects
# it. Measured 2026-08-24:
#
#   $ opa eval -d b.rego -i p.json 'data.b.hit'      -> {} , no error
#   $ opa eval -d b.rego -i p.json --strict-builtin-errors ...
#     "regex.match: error parsing regexp: invalid or unsupported Perl syntax: `(?!`"
#
# Without that flag a regex the engine cannot compile makes `regex.match`
# UNDEFINED, the rule body fails, and the rule silently permits everything it
# was written to refuse. A guard that cannot compile reports the same thing as a
# guard that found nothing wrong. That is the exit-0-is-not-proof-of-work class
# wearing a new hat, and it is worse here than in Python, where a bad pattern
# raises at import.
#
# So the flag is not the guard. Every rule below carries `must_match` and
# `must_not_match`, and `broken` fires when a rule stops agreeing with its own
# two examples -- whatever the reason, compile failure included. The adapter
# queries `broken` on every call and refuses loudly when it is non-empty, so a
# policy that breaks blocks work and says which rule broke, rather than waving
# everything through in silence.
#
#   conftest test --policy policy policy/fixtures/command_*.json
package command

import rego.v1

# Each rule is: the pattern, the escape marker that turns it off, the message,
# and the two examples that prove the pattern still works.
#
# The messages are verbatim from rule-guard.py. They are the expensive part --
# each one names the incident that paid for the rule and the command to run
# instead -- and rewording them while moving them would lose the receipts.
rules := [
	{
		"id": "add_all",
		"re": `\bgit\s+(?:-\S+\s+|--\S+(?:=\S+)?\s+)*add\s+(?:-A\b|--all\b|\.(?:\s|$))`,
		"marker": "add-all-intended",
		"must_match": "git add -A",
		"must_not_match": "git add -- path/one path/two",
		"msg": concat("", [
			"BLOCKED by rule-guard: `git add -A` / `git add .` in this estate.\n",
			"store/ and storage/ are tracked runtime state that pytest writes to, so this ",
			"stages another process's test output.\n",
			"Stage explicit paths instead:  git add -- path/one path/two",
		]),
	},
	{
		"id": "no_verify",
		# `[^|;&]*` also crosses NEWLINES, so in a multi-line script it scanned
		# past the end of the commit and matched a `-n` on any later line --
		# `rg -n`, `tail -n`, `sort -n`. Measured 2026-08-19: a `git commit`
		# followed three lines later by `rg -n` was refused. The line
		# terminators are excluded for that reason; keep them excluded.
		"re": `\bgit\s+commit\b[^|;&\n\r]*(?:--no-verify\b|\s-n\b)`,
		"marker": "no-verify-intended",
		"must_match": "git commit -m x --no-verify",
		"must_not_match": "git commit -m x\nrg -n foo",
		"msg": concat("", [
			"BLOCKED by rule-guard: `git commit --no-verify`.\n",
			"The permission classifier has refused this twice already. Use the isolated ",
			"worktree, or state why the gate must be skipped.",
		]),
	},
	{
		"id": "index_lock",
		"re": `\brm\b[^|;&]*index\.lock`,
		"marker": "lock-removal-intended",
		"must_match": "rm -f .git/index.lock",
		"must_not_match": "ls .git/index.lock",
		"msg": concat("", [
			"BLOCKED by rule-guard: removing .git/index.lock.\n",
			"Sessions share one index here. That lock is another session's commit in ",
			"progress; deleting it corrupts their commit. Queue and wait.",
		]),
	},
	{
		"id": "autoscale_enable",
		"re": `\bgh\s+workflow\s+enable\b[^|;&\n]*(?:337731742|ci-autoscale|CI\s+autoscale)`,
		"marker": "autoscale-intended",
		"must_match": "gh workflow enable 337731742",
		"must_not_match": "gh workflow list",
		"msg": concat("", [
			"BLOCKED by rule-guard: re-enabling the CI autoscale workflow.\n",
			"It was turned off on 2026-08-19 by founder decision after it stopped Fly ",
			"machines mid-build and killed nine PRs, including its own merge commit.\n",
			"It may only come back when the busy-runner read is proven (needs a repo-admin ",
			"PAT secret) AND the founder says the fleet is reliable.",
		]),
	},
	{
		"id": "autoscale_run",
		"re": `runners\.sh\s+autoscale\b`,
		"marker": "autoscale-intended",
		"must_match": "deploy/runners.sh autoscale",
		"must_not_match": "deploy/runners.sh status",
		"msg": concat("", [
			"BLOCKED by rule-guard: `deploy/runners.sh autoscale`.\n",
			"Its scale-down reads the busy-runner list with `|| true`; when that read fails ",
			"the list is empty, every machine reads as idle, and it stops runners that are ",
			"mid-build. That is what killed PRs #383 #387 #390 #391 #407 #414 #424 #427 ",
			"#431 on 2026-08-19.\n",
			"Scale by hand with `fly machine start`, or fix the fail-open read first.",
		]),
	},
	{
		"id": "autoscale_stop_ci",
		"re": `\bfly\s+machine[s]?\s+stop\b[^|;&\n]*prospector-ci`,
		"marker": "autoscale-intended",
		"must_match": "fly machine stop 1234 -a prospector-ci",
		"must_not_match": "fly machine list -a prospector-ci",
		"msg": concat("", [
			"BLOCKED by rule-guard: stopping a machine in the CI fleet `prospector-ci`.\n",
			"A stopped runner mid-job fails as \"The self-hosted runner lost communication ",
			"with the server\", which reads as a failing test and costs a session to ",
			"diagnose. Check the GitHub busy list first, then re-run with the marker.",
		]),
	},
	{
		"id": "clone_standby",
		"re": `\bfly\s+m(?:achine)?s?\s+clone\b`,
		"marker": "clone-standby-intended",
		"must_match": "fly machine clone 8e4530a7712248 -a prospector-ci",
		"must_not_match": "fly machine list -a prospector-ci",
		"msg": concat("", [
			"BLOCKED by rule-guard: `fly machine clone`.\n",
			"On an app with no services -- prospector-ci and hermes-ci are both service-less ",
			"by design -- a clone is created as a STANDBY of its source (`config.standbys`). ",
			"Fly stops a started standby on purpose, so it registers as a GitHub runner, ",
			"takes a job, and dies mid-build as \"The self-hosted runner lost communication ",
			"with the server\".\n",
			"Measured 2026-08-19: 10 of 12 prospector-ci machines were clones. Real capacity ",
			"was 2 while every count on every screen said 12.\n",
			"Grow the fleet with `fly scale count <n> -a <app>`, which makes real machines. ",
			"Repair an existing clone with ",
			"`fly machine update <id> -a <app> --standby-for \"\" --yes`.",
		]),
	},
	{
		"id": "shared_stash",
		# `git stash list` and `git stash show` are reads and stay allowed.
		# `git stash push` is allowed too: pushing only ever ADDS an entry, and
		# the damage is in taking one off.
		"re": `\bgit\s+stash\s+(pop|apply|drop|clear)\b`,
		"marker": "stash-intended",
		"must_match": "git stash pop",
		"must_not_match": "git stash list",
		"msg": concat("", [
			"BLOCKED by rule-guard: taking an entry off the shared stash.\n",
			"refs/stash lives in the COMMON git dir, so every worktree and every concurrent ",
			"session shares one stack. The top entry is very likely not yours.\n",
			"On 2026-08-19 this popped another branch's WIP into a detached worktree and ",
			"conflicted; on 2026-08-07 it dropped an entry that had to be recovered.\n",
			"Read it first:  git stash list && git stash show -p stash@{0}\n",
			"To save your own work, commit on a branch instead of stashing.",
		]),
	},
	{
		"id": "fly_revival",
		# Teardown (destroy, suspend) and read-only commands (status, list,
		# logs) are absent from this pattern on purpose: the ruled path is the
		# EXIT, so tearing Fly down must stay possible.
		"re": `\bfly(?:ctl)?\s+(?:apps\s+restart|machines?\s+(?:start|run|clone|restart|update)|deploy\b|launch\b|scale\s|secrets\s+(?:set|import)|resume\b|volumes\s+create|ips\s+allocate|certs\s+add|postgres\s+create)`,
		"marker": "fly-revival-intended",
		"must_match": "fly deploy -a prospector",
		"must_not_match": "fly apps destroy prospector",
		"msg": concat("", [
			"BLOCKED by rule-guard: this revives something on Fly.\n",
			"Founder ruling R1 (2026-08-24), verbatim: \"for the last time, we are not ",
			"going back to fly\".\n",
			"Teardown and read-only Fly commands pass. The work goes to the exit instead: ",
			"crew#78 (k8s) / crew#38 (drill the exit). Standing rulings: ",
			"~/.claude/scripts/rulings.json",
		]),
	},
	{
		"id": "force_push",
		# REWRITTEN FOR RE2. The Python was:
		#   --force(?!-with-lease|-if-includes)\b
		# and RE2 has no lookahead. `\b` alone cannot do the job, because `-` is
		# a non-word character, so `--force-with-lease` satisfies `--force\b`.
		#
		# `(?:[^\w-]|$)` says the same thing positively: the character after
		# `--force` must exist and be neither a word character nor a hyphen, or
		# there must be no character at all. That admits `--force origin`,
		# `--force`, and refuses `--force-with-lease` and `--force-if-includes`
		# without naming either of them -- so a third safe spelling git adds
		# later is admitted automatically, which the lookahead version could not
		# do. differential.py proves this agrees with the Python on every case.
		"re": `\bgit\s+(?:-\S+\s+|--\S+(?:=\S+)?\s+)*push\b[^|;&\n]*?(?:--force(?:[^\w-]|$)|-f\b|\s\+(?:refs/)?[\w.][\w./\-]*:)`,
		"marker": "force-push-intended",
		"must_match": "git push --force origin br",
		"must_not_match": "git push --force-with-lease origin br",
		"msg": concat("", [
			"BLOCKED by rule-guard: bare force-push.\n",
			"The remote moves on its own here. automerge.yml updates every open PR branch ",
			"whenever main moves, so your branch very likely has a commit you have not ",
			"fetched -- measured twice on 2026-08-19 (c2a85a4c, 6534d51c).\n",
			"git's non-fast-forward rejection is what catches that, and --force is the flag ",
			"that switches it off.\n",
			"Do this instead:  git fetch origin && git merge origin/<branch>\n",
			"If you truly must rewrite, use the form that still refuses a moved remote:\n",
			"  git push --force-with-lease origin <branch>",
		]),
	},
	{
		"id": "push_main",
		# REWRITTEN FOR RE2. The Python was `main\b(?![-/])`. `\b` already
		# requires a non-word character next, and the lookahead then excluded
		# two of them. `(?:[^\w/-]|$)` states the whole condition once: the next
		# character must be absent, or be neither a word character, a slash, nor
		# a hyphen. So `main-ci` and `main/foo` pass and `main` is refused.
		"re": `\bgit\s+push\b[^\n|;&]*\s(?:\+?(?:HEAD|\S+):)?(?:refs/heads/)?main(?:[^\w/-]|$)`,
		"marker": "direct-push-intended",
		"must_match": "git push origin main",
		"must_not_match": "git push origin main-ci",
		"msg": concat("", [
			"BLOCKED by rule-guard: direct push to main.\n",
			"main's gates run on pull requests; a direct push lands ungraded content. The ",
			"string-findings defect of 2026-08-24 (1a97e80) reached crew main this way and ",
			"broke the next PR's qa.\n",
			"Do this instead: push a branch and open a PR -- the merge-when-green poller ",
			"lands it when qa and review-gate pass.",
		]),
	},
	{
		"id": "paid_hetzner",
		"re": `\bhcloud\s+(?:server|volume|load-balancer|primary-ip|floating-ip)\s+create\b`,
		"marker": "founder-approved-spend",
		"must_match": "hcloud server create --type cx22 --name k3s-1",
		"must_not_match": "hcloud server list",
		"msg": paid_infra_msg("Hetzner Cloud"),
	},
	{
		"id": "paid_digitalocean",
		"re": `\bdoctl\s+(?:compute\s+(?:droplet|load-balancer)|databases?|kubernetes\s+cluster)\s+create\b`,
		"marker": "founder-approved-spend",
		"must_match": "doctl kubernetes cluster create prod --region lon1",
		"must_not_match": "doctl kubernetes cluster list",
		"msg": paid_infra_msg("DigitalOcean"),
	},
	{
		"id": "paid_aws",
		"re": `\baws\s+(?:ec2\s+run-instances|eks\s+create-cluster|rds\s+create-db-instance)\b`,
		"marker": "founder-approved-spend",
		"must_match": "aws eks create-cluster --name prod",
		"must_not_match": "aws ec2 describe-instances",
		"msg": paid_infra_msg("AWS"),
	},
	{
		"id": "paid_gcp",
		"re": `\bgcloud\s+(?:compute\s+instances\s+create|container\s+clusters\s+create|sql\s+instances\s+create)\b`,
		"marker": "founder-approved-spend",
		"must_match": "gcloud container clusters create prod --zone europe-west2-a",
		"must_not_match": "gcloud container clusters list",
		"msg": paid_infra_msg("Google Cloud"),
	},
	{
		"id": "paid_azure",
		"re": `\baz\s+(?:vm\s+create|aks\s+create|container\s+create)\b`,
		"marker": "founder-approved-spend",
		"must_match": "az aks create --name prod -g rg-prod",
		"must_not_match": "az aks list",
		"msg": paid_infra_msg("Azure"),
	},
	{
		"id": "paid_linode",
		"re": `\blinode-cli\s+linodes\s+create\b`,
		"marker": "founder-approved-spend",
		"must_match": "linode-cli linodes create --type g6-standard-1",
		"must_not_match": "linode-cli linodes list",
		"msg": paid_infra_msg("Linode"),
	},
	{
		"id": "paid_vultr",
		"re": `\bvultr-cli\s+instance\s+create\b`,
		"marker": "founder-approved-spend",
		"must_match": "vultr-cli instance create --region lhr",
		"must_not_match": "vultr-cli instance list",
		"msg": paid_infra_msg("Vultr"),
	},
	{
		"id": "paid_scaleway",
		"re": `\bscw\s+instance\s+server\s+create\b`,
		"marker": "founder-approved-spend",
		"must_match": "scw instance server create type=DEV1-S",
		"must_not_match": "scw instance server list",
		"msg": paid_infra_msg("Scaleway"),
	},
	{
		"id": "paid_terraform_apply",
		# A plan's cost is invisible from the command line, which is exactly why
		# applying one is the moment to stop. Planning and destroying stay free --
		# see must_not_match, and `terraform destroy` in permitted_commands below.
		"re": `\b(?:terraform|tofu)\s+apply\b`,
		"marker": "founder-approved-spend",
		"must_match": "terraform apply -auto-approve",
		"must_not_match": "terraform plan -out=tfplan",
		"msg": paid_infra_msg("whatever the plan provisions"),
	},
	{
		"id": "paid_pulumi_up",
		"re": `\bpulumi\s+up\b`,
		"marker": "founder-approved-spend",
		"must_match": "pulumi up --yes",
		"must_not_match": "pulumi preview",
		"msg": paid_infra_msg("whatever the stack provisions"),
	},
	# make guard inserts here
]

# Ten rules share one message, so it is written once. Ten copies of a paragraph this
# long is nine chances for the ruling to be paraphrased into something the founder
# did not say.
#
# WHAT PAID FOR THESE TEN RULES. On 2026-08-24 I told the founder a rented Hetzner
# box at EUR 3.79/month was "the only thing between the merged manifests and a
# cluster", and that it was his call because it was money. Both halves were wrong:
# k3d runs a real cluster on this laptop for nothing, and he had already answered
# the question twice. His ruling closed it, and his fourth enforcement step was
# that the refusal be mechanical rather than remembered -- a session that has
# already asked does not get to ask again in different words.
paid_infra_msg(provider) := concat("", [
	"BLOCKED by rule-guard: this provisions infrastructure that costs money (", provider, ").\n",
	"Founder ruling R14 (2026-08-24), verbatim: \"Mac is the prove-and-build substrate. ",
	"Full stop. NO paid infra without explicit founder sign-off. Free tier only (Oracle ",
	"Always Free, GitHub-hosted runners, etc.). If it costs >EUR 0, it waits until after ",
	"prove-and-build is done. Real cluster follows proof, never precedes it.\"\n",
	"Prove it on the substrate first: deploy/rehearse_cluster.sh runs a real k3d cluster ",
	"on this laptop for EUR 0. Reading, planning and destroying are all still allowed.\n",
	"Standing rulings: ~/.claude/scripts/rulings.json",
])

# ---------------------------------------------------------------------------
# The decision.
# ---------------------------------------------------------------------------

deny contains msg if {
	some r in rules
	not contains(input.command, r.marker)
	regex.match(r.re, input.command)
	msg := sprintf(
		"%s\n\nIf you mean it, append  # %s  to the command and say in your reply why this case is different.",
		[r.msg, r.marker],
	)
}

# ---------------------------------------------------------------------------
# The policy's opinion of itself. See the header: an uncompilable regex makes
# regex.match undefined rather than raising, so a rule can stop working and the
# only visible symptom is that nothing is ever refused again.
#
# `broken` is what the adapter checks BEFORE it trusts `deny`. It is kept out of
# `deny` deliberately: a broken rule must not blend into the list of refusals a
# session sees, because the two need opposite responses -- a refusal means fix
# the command, a breakage means fix the policy and trust nothing until it is.
# ---------------------------------------------------------------------------

broken contains msg if {
	some r in rules
	not regex.match(r.re, r.must_match)
	msg := sprintf(
		"rule %q no longer matches its own must_match example %q. Either the pattern is wrong or RE2 cannot compile it -- run `opa eval --strict-builtin-errors` to see which. Until this is fixed the rule refuses nothing.",
		[r.id, r.must_match],
	)
}

broken contains msg if {
	some r in rules
	regex.match(r.re, r.must_not_match)
	msg := sprintf(
		"rule %q matches %q, which it must permit. A guard that refuses correct work is an outage (LAW 38).",
		[r.id, r.must_not_match],
	)
}

# The marker has to actually turn the rule off, or the escape hatch documented
# in every message above is a lie and a session that follows the instructions
# is refused twice.
broken contains msg if {
	some r in rules
	regex.match(r.re, r.must_match)
	marked := sprintf("%s  # %s", [r.must_match, r.marker])
	contains(marked, r.marker)
	regex.match(r.re, marked)
	not_off := deny_would_fire(r, marked)
	not_off
	msg := sprintf(
		"rule %q still fires when its own override marker %q is present. The escape hatch its message advertises does not work.",
		[r.id, r.marker],
	)
}

# ---------------------------------------------------------------------------
# THE HALF THAT MATTERS MORE. A rule's own `must_not_match` proves that ONE rule
# permits ONE command. It cannot prove that the policy as a whole still permits
# the work the estate is made of, because the rule that breaks that is usually a
# different rule from the one you were editing.
#
# Every command below is one no session may ever be refused. `k3d cluster create`
# is the load-bearing case: R14 makes this laptop the substrate, so a policy that
# refused it would leave the estate with no way to run a cluster at all -- the
# guard would have caused the outage the ruling exists to prevent (LAW 38).
#
# This check is not about the ten paid_* rules. It applies to all of them, and to
# every rule added after this one, which is the point: the fence that is going to
# refuse correct work has not been written yet.
# ---------------------------------------------------------------------------

permitted_commands := [
	"k3d cluster create prospector-rehearsal --agents 0 --wait --timeout 900s",
	"k3d cluster delete prospector-rehearsal",
	"kind create cluster --name prospector",
	"minikube start --driver=docker",
	"kubectl create namespace prospector",
	"kubectl apply -k deploy/k8s/overlays/staging",
	"docker run --rm --user 10001:10001 --read-only prospector-store-api:local",
	# R14 names Oracle Always Free as permitted, and no command line distinguishes
	# a free ARM shape from a billable one -- so the oci CLI is deliberately not
	# fenced, and this case is here to keep it that way.
	"oci compute instance launch --shape VM.Standard.A1.Flex",
	"terraform plan -out=tfplan",
	"terraform destroy -auto-approve",
	"hcloud server list",
	"hcloud server delete 12345",
	"aws ec2 describe-instances",
	"git push origin my-branch",
	"git fetch origin",
	"git add -- path/one path/two",
]

broken contains msg if {
	some cmd in permitted_commands
	some r in rules
	not contains(cmd, r.marker)
	regex.match(r.re, cmd)
	msg := sprintf(
		"rule %q refuses %q, which is on the permitted_commands list: work the estate must always be able to do. A guard that refuses correct work is an outage (LAW 38). Narrow the pattern, or say in the pull request why that command should stop being permitted.",
		[r.id, cmd],
	)
}

deny_would_fire(r, cmd) if {
	not contains(cmd, r.marker)
	regex.match(r.re, cmd)
}

# ---------------------------------------------------------------------------
# A settings store printed WHOLESALE, when the same tool prints names only.
#
# This one arrived from the other side of the 2026-08-24 merge, where it was
# `rule_secret_store_dump` in rule-guard.py. R16 says a refusal decidable from
# the command string is Rego, so it lands here rather than as a seventh Python
# rule -- which the ceiling in hand_rolled_policy.rego would have refused.
#
# THE CLASS, without naming any one command: a tool that holds a store of
# settings prints the VALUES by default, and the same tool will print only the
# NAMES if asked. An agent reaching for the default is not choosing to publish;
# it is answering "what is configured here?" and getting the values as a side
# effect it cannot take back, because the transcript is written before it reads
# the output.
#
# Two instances paid for it. `docker compose config` expands every env_file
# value inline: on 2026-08-24 one command put live credentials into 1,314 files,
# 12,688 occurrences. `gh api .../actions/variables` the same day put a Stripe
# key into a transcript; that one was pk_live_, public by design and needing no
# rotation, which is exactly why it is the useful instance -- the mistake was
# free once.
#
# WHY THESE HAVE AN `unless` AND THE TABLE ABOVE DOES NOT. The Python spelled
# the exemptions as negative lookahead, which RE2 cannot compile at all. Stated
# positively they are a second pattern: `re` is what the command does, `unless`
# is the same tool asked the safe way. That is expressible in RE2 and reads
# better than the lookahead did.
# ---------------------------------------------------------------------------

value_dump_marker := "value-dump-intended"

value_dumps := [
	{
		"id": "compose_config",
		"re": `\bdocker\s+compose\b[^\n;&|]*\bconfig\b`,
		"unless": `\bdocker\s+compose\b[^\n;&|]*(?:--quiet|\s-q\b|--services|--images|--volumes|--profiles|--hash)`,
		"dumps": "docker compose config expands every env_file value inline",
		"instead": "docker compose config --quiet (it validates and prints nothing)",
		"must_match": "docker compose -f deploy/compose/docker-compose.yml config",
		"must_not_match": "docker compose config --quiet",
	},
	{
		"id": "docker_inspect",
		"re": `\bdocker\s+(?:container\s+)?inspect\b`,
		# `>/dev/null` is in the exemption because deploy/rehearse_cluster.sh:619
		# runs `docker inspect "$srv" >/dev/null 2>&1` purely to ask "does this
		# container exist?". Nothing is printed, so nothing can be read again,
		# which is the entire thing LAW 21 protects.
		"unless": `\bdocker\s+(?:container\s+)?inspect\b[^\n;&|]*(?:--format|\s-f\b|>\s*/dev/null)`,
		"dumps": "bare docker inspect prints .Config.Env",
		"instead": "docker inspect --format '{{.State.Running}}' (name the field you want)",
		"must_match": "docker inspect opsconsole-diag2",
		"must_not_match": "docker inspect --format '{{.State.Running}}' opsA",
	},
	{
		"id": "gh_actions_store",
		"re": `\bgh\s+api\b[^\n;&|]*actions/(?:variables|secrets)\b`,
		"dumps": "gh api actions/variables returns every variable's value",
		"instead": "add --jq '.variables[].name' (this rule passes when the command says .name and never .value)",
		"must_match": "gh api repos/chidionyema/prospector/actions/variables",
		"must_not_match": "gh api repos/chidionyema/prospector/actions/runners",
	},
	{
		"id": "gh_variable_list",
		"re": `\bgh\s+variable\s+list\b`,
		"unless": `\bgh\s+variable\s+list\b[^\n;&|]*--json\s`,
		"dumps": "gh variable list prints values in the second column",
		"instead": "gh variable list --json name",
		"must_match": "gh variable list",
		"must_not_match": "gh variable list --json name",
	},
	{
		"id": "kubectl_secret_dump",
		"re": `\bkubectl\s+get\s+secrets?\b[^\n;&|]*-o(?:utput)?[= ]\s*(?:yaml|json)`,
		"dumps": "kubectl get secret -o yaml prints the base64 of every key",
		"instead": "kubectl describe secret NAME (it prints key names and byte counts)",
		"must_match": "kubectl get secret prospector-engine-env -o yaml",
		"must_not_match": "kubectl describe secret prospector-engine-env",
	},
	{
		"id": "printenv_all",
		"re": `(?:^|[;&|]\s*)printenv\s*(?:$|[|;&\n])`,
		"dumps": "printenv with no argument prints the whole environment",
		"instead": "printenv NAME, or test the value without printing it",
		"must_match": "printenv",
		"must_not_match": "printenv PROSPECTOR_STORE_DIR",
	},
	{
		"id": "env_all",
		"re": `(?:^|[;&|]\s*)env\s*(?:$|\|)`,
		"dumps": "env with no argument prints the whole environment",
		"instead": "printenv NAME, or test the value without printing it",
		"must_match": "env",
		"must_not_match": "env PROSPECTOR_STORE_DIR=/data/store python3 run.py",
	},
]

# A backslash continuation puts the safe flag on the NEXT line -- crew/ARCHITECTURE.md:56
# is a real instance -- so the lines are joined before matching, exactly as the
# Python did. LAW 38: a guard that refuses correct work is an outage.
value_dump_input(cmd) := regex.replace(cmd, `\\\n\s*`, " ")

# The whole point is that these tools CAN answer without values. A jq or format
# expression that asks for names and never asks for values is that answer.
names_only(cmd) if {
	contains(cmd, ".name")
	not contains(cmd, ".value")
}

value_dump_exempt(r, cmd) if regex.match(object.get(r, "unless", `\bZZZ_NEVER_MATCHES_ZZZ\b`), cmd)

value_dump_exempt(_, cmd) if names_only(cmd)

value_dump_fires(r, cmd) if {
	not contains(cmd, value_dump_marker)
	regex.match(r.re, cmd)
	not value_dump_exempt(r, cmd)
}

deny contains msg if {
	some r in value_dumps
	cmd := value_dump_input(input.command)
	value_dump_fires(r, cmd)
	msg := sprintf(
		"BLOCKED by rule-guard: this prints a settings store's VALUES.\n  %s.\n  Ask for names instead: %s\nLAW 21: a secret value never appears anywhere it can be read again -- not a transcript, not a log line, not a commit. Naming a secret is fine; printing it is not.\n\nIf you mean it, append  # %s  to the command and say in your reply why this case is different.",
		[r.dumps, r.instead, value_dump_marker],
	)
}

# The same self-proof the table above gets. A rule that stops agreeing with its
# own two examples -- RE2 refusing to compile the pattern included -- reports
# broken rather than silently permitting everything it was written to refuse.
broken contains msg if {
	some r in value_dumps
	not value_dump_fires(r, value_dump_input(r.must_match))
	msg := sprintf(
		"value-dump rule %q no longer refuses its own must_match example %q. Until this is fixed the rule refuses nothing.",
		[r.id, r.must_match],
	)
}

broken contains msg if {
	some r in value_dumps
	value_dump_fires(r, value_dump_input(r.must_not_match))
	msg := sprintf(
		"value-dump rule %q refuses its own must_not_match example %q, which is the names-only form of the same tool. A guard that refuses correct work is an outage (LAW 38).",
		[r.id, r.must_not_match],
	)
}

broken contains msg if {
	some cmd in permitted_commands
	some r in value_dumps
	value_dump_fires(r, value_dump_input(cmd))
	msg := sprintf(
		"value-dump rule %q refuses %q, which is on the permitted_commands list: work the estate must always be able to do (LAW 38).",
		[r.id, cmd],
	)
}

# ---------------------------------------------------------------------------
# Incident, 2026-08-25 02:40 (crew#212): `docker buildx build --platform linux/arm64`
# ran for 75 minutes on the x86_64 colima VM. The build ran `yarn install` under
# qemu-aarch64: VM memory fell to 83 MB free, load reached 99, the host throttled
# to 51% and the founder's Finder and Save dialog froze. Founder: "this must never
# happen again."
#
# The class: building for a platform the engine does not run natively. Emulation
# costs 10-20x CPU and the VM has no memory headroom. The adapter passes the
# machine's own arch as input.arch, so no arch is written here (LAW 46).
# ---------------------------------------------------------------------------

native_platform := {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}[input.arch]

foreign_platform_marker := "foreign-platform-intended"

foreign_platform_re := `(?:--platform[= ]+|DOCKER_DEFAULT_PLATFORM=)["']?linux/([a-z0-9]+)`

requested_platforms contains p if {
	regex.match(`\b(?:docker\s+(?:buildx\s+)?build|docker\s+compose\s+.*\bbuild|DOCKER_DEFAULT_PLATFORM=)`, input.command)
	some m in regex.find_all_string_submatch_n(foreign_platform_re, input.command, -1)
	p := m[1]
}

deny contains msg if {
	not contains(input.command, foreign_platform_marker)
	some p in requested_platforms
	p != native_platform
	msg := sprintf(
		"BLOCKED by rule-guard: a docker build for linux/%s on a %s engine runs under qemu emulation.\nOn 2026-08-25 one such build (`--platform linux/arm64`, backstage-keytar-proof) took the colima VM to 83 MB free and load 99 and froze the founder's Mac for over an hour (crew#212).\nBuild for the native platform (linux/%s), or let CI build the foreign one: .github/workflows already runs the multi-arch matrix on GitHub's runners.\n\nIf you mean it, append  # %s  to the command and say in your reply why this case is different.",
		[p, input.arch, native_platform, foreign_platform_marker],
	)
}

# The rule's opinion of itself: it must refuse a foreign build and permit a native one.
broken contains msg if {
	native := native_platform
	foreign := {"amd64": "arm64", "arm64": "amd64"}[native]
	not count(deny) > 0 with input as {"command": sprintf("docker buildx build --platform linux/%s -t x .", [foreign]), "arch": input.arch}
	msg := "rule foreign_platform no longer refuses its own foreign-build example; until this is fixed it refuses nothing."
}

broken contains msg if {
	native := native_platform
	count(deny) > 0 with input as {"command": sprintf("docker buildx build --platform linux/%s -t x .", [native]), "arch": input.arch}
	msg := "rule foreign_platform refuses a native build, which is an outage (LAW 38)."
}
