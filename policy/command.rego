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
	# make guard inserts here
]

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

deny_would_fire(r, cmd) if {
	not contains(cmd, r.marker)
	regex.match(r.re, cmd)
}
