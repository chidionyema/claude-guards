# Definition of Done, as data instead of code. Moved out of dod-guard.py on the follow-up its
# own 2026-08-26 legacy entry named: "a Stop runner, then dod-guard ... move to policy/reply.rego
# and leave this list." opa-hook.py became that Stop runner on crew#281 CP2 -- its own docstring
# says so: "That is the Stop runner hand_rolled_policy.rego was waiting for." So the reason
# dod-guard.py's rules stayed Python (no runner existed) no longer holds.
#
# Landed here as its own package rather than folded into policy/reply.rego, because the input is
# different: reply.rego reads `input.reply` with fenced code blocks already blanked (opa-hook.py's
# last_reply_above_fold), so it can never see a fence's own content. The 2026-09-15 LAW 31 rule
# below (a bare ```bash block handed to the founder to type) has to read the fence's CONTENTS,
# so it needs the text BEFORE that blanking -- above the fold, nothing stripped. A second input
# shape needs a second package; jamming it into `reply` would mean either reply.rego loses the
# fence-blanking every other rule there depends on, or this rule silently never fires.
#
# dod-guard.py is the adapter: it reads the transcript, cuts the text at the first `---` line
# (above_the_fold, unchanged from before this migration -- nothing here needs it touched), reads
# the reply's first word (first_word, likewise unchanged), and asks `data.dod.deny` for the rest.
# It still owns two things Rego cannot: the transcript read, and the per-session "never block the
# same text twice, at most three times" state file -- neither is a decision, both are state.
#
#   conftest test --policy policy policy/fixtures/dod
#   opa test policy/dod.rego policy/dod_test.rego
package dod

import rego.v1

handoff := ["Built:", "Use:", "Expect:", "Not done:", "Evidence:"]

# `label` here is always a literal like "Built:" or "Evidence:" -- none of the labels this file
# calls with contain a regex metacharacter, so unlike Python's re.escape(label) call this can
# concatenate the label straight into the pattern.
label_re(label) := concat("", [`(?i)^\s*(?:[-*\d.]+\s*)?\**\s*`, label])

checkable_re := "https?://\\S+|\\b[0-9a-f]{7,40}\\b|`[^`]+`|(?:~|/)[\\w./-]+"

has_line(text, label) if {
	some line in split(text, "\n")
	regex.match(label_re(label), line)
}

# The first line matching `label:`, split on its FIRST colon only (a value may itself contain
# one, e.g. a URL). `min()` over the matching indices is what gives "first match", the same as
# Python's `for line in text.splitlines(): ... return`.
label_line_indices(text, label) := {i |
	lines := split(text, "\n")
	some i
	regex.match(label_re(label), lines[i])
}

line_value(text, label) := val if {
	idxs := label_line_indices(text, label)
	count(idxs) > 0
	line := split(text, "\n")[min(idxs)]
	colon := indexof(line, ":")
	colon >= 0
	val := substring(line, colon + 1, -1)
}

evidence_is_checkable(text) if {
	some line in split(text, "\n")
	regex.match(label_re("Evidence:"), line)
	colon := indexof(line, ":")
	colon >= 0
	regex.match(checkable_re, substring(line, colon + 1, -1))
}

# DONE:/INVENTORY: shape (Definition of Done v2.1, founder 2026-08-25).

deny contains msg if {
	input.kind == "DONE"
	not has_line(input.reply, "Founder receipt:")
	msg := "DONE: needs a `Founder receipt:` line. If the founder has not used it and confirmed it, the word is INVENTORY:, not DONE:."
}

deny contains msg if {
	input.kind == "DONE"
	not has_line(input.reply, "Evidence:")
	msg := "DONE: needs an `Evidence:` line."
}

deny contains msg if {
	input.kind == "INVENTORY"
	missing := [h | some h in handoff; not has_line(input.reply, h)]
	count(missing) > 0
	msg := sprintf(
		"INVENTORY: needs all five handoff lines; missing %s",
		[concat(", ", [sprintf("`%s`", [m]) | some m in missing])],
	)
}

# crew#281: a staged handoff carries its own default and timer, in the founder's words.
deny contains msg if {
	input.kind == "STAGED"
	not regex.match("Reply 'go' to execute immediately, 'hold' to review", input.reply)
	msg := "STAGED: needs the sentence `Reply 'go' to execute immediately, 'hold' to review.`"
}

deny contains msg if {
	input.kind == "STAGED"
	not regex.match(`Auto-activating in \d+ minutes`, input.reply)
	msg := "STAGED: needs `Auto-activating in <N> minutes.` with a number."
}

deny contains msg if {
	input.kind in {"DONE", "INVENTORY"}
	has_line(input.reply, "Evidence:")
	not evidence_is_checkable(input.reply)
	msg := "`Evidence:` must contain a URL, a commit hash, a file path or a `command`."
}

# DoD v3 (founder, 2026-09-15): "done means commercially ready and viable", then, after a fork's
# own reply proved the first draft too weak, "a one-off curl the builder ran itself does not
# count, no matter how real the response." A `Built:` line (INVENTORY) or the reply's own opening
# line (DONE) that claims the thing is LIVE needs `Evidence:` to show an independent live check --
# a `kubectl`/`idp-kube get ...` reference showing `Running`, or a named independent verifier
# (`qa-agent`, the estate's standing drill) -- never a bare test command, a link, or a curl the
# builder ran against its own process.
live_claim_re := `(?i)\bon cluster\b|\blive\b|\bdeployed\b|\bdoor(?:ed)?\b|\brunning\b|\breachable\b`

kube_get_re := `(?i)\b(?:kubectl|idp-kube)\s+\S*\s*get\b`

kube_running_re := `\bRunning\b`

independent_verifier_re := `(?i)\bqa-agent\b|\blogin-drill\b|\bthe drill\b|\bindependently\s+verif\w*\b`

live_evidence_is_independent(evidence) if regex.match(independent_verifier_re, evidence)

live_evidence_is_independent(evidence) if {
	regex.match(kube_get_re, evidence)
	regex.match(kube_running_re, evidence)
}

evidence_text := val if {
	val := line_value(input.reply, "Evidence:")
} else := ""

claim_line := val if {
	input.kind == "INVENTORY"
	val := line_value(input.reply, "Built:")
}

claim_line := val if {
	input.kind == "DONE"
	lines := split(trim_space(input.reply), "\n")
	count(lines) > 0
	val := lines[0]
}

deny contains msg if {
	claim := trim_space(claim_line)
	claim != ""
	regex.match(live_claim_re, claim)
	not live_evidence_is_independent(evidence_text)
	msg := sprintf(
		concat("", [
			"DoD v3: this claims the thing is live (\"%s\") but `Evidence:` does not show an ",
			"independent live check. A test command, a PR/commit link, or a curl the builder ran ",
			"against its own process is not enough -- add a `kubectl`/`idp-kube get ...` reference ",
			"that shows Running, or `qa-agent`'s sign-off, or say `Not done:` instead.",
		]),
		[substring(claim, 0, 160)],
	)
}

# LAW 31 -- "the founder does not run scripts" (2026-08-26 incident, sharpened 2026-09-10 after
# three replies in one session handed him a shell command, an installer and a policy to
# authorise, and nothing refused any of them). Applies to EVERY reply kind, not only DONE/
# INVENTORY: handing him work is a defect whatever word the reply opens with.
#
# Not an offence: a command quoted as EVIDENCE of what was run -- the Evidence:/Not done:/Built:/
# Use:/Expect:/Founder receipt: lines themselves, and a table row or a quotation.
evidence_prefix_skip_re := `(?i)^(?:Evidence|Not done|Founder receipt|Built|Use|Expect)\s*:`

names_a_tool_re := "(?i)\\b(?:run|use|execute|invoke)\\s+`?bin/idp-[a-z0-9-]+"

ask_to_run_re := `(?i)\b(?:please\s+|just\s+|now\s+|you\s+|you'll\s+|you need to\s+|you should\s+|run this|then run|execute this|type this|paste this|copy this)\b[^.]{0,80}?\b(?:run|execute|type|paste|invoke|install)\b`

asks_permission_re := `(?i)\b(?:authorise|authorize|approve|paste it|paste the|confirm and I|say go and I|your call to apply|tell me to apply)\b`

# First match wins, same order Python checked them in: naming a tool, then asking him to run,
# then asking him to authorise.
law31_line_offence(line) := "names an estate tool as his action" if {
	regex.match(names_a_tool_re, line)
}

law31_line_offence(line) := "asks him to run something" if {
	not regex.match(names_a_tool_re, line)
	regex.match(ask_to_run_re, line)
}

law31_line_offence(line) := "asks him to authorise something the estate can do itself" if {
	not regex.match(names_a_tool_re, line)
	not regex.match(ask_to_run_re, line)
	regex.match(asks_permission_re, line)
}

deny contains msg if {
	some raw in split(input.reply, "\n")
	line := trim_space(raw)
	line != ""
	not regex.match(evidence_prefix_skip_re, line)
	not startswith(line, "|")
	not startswith(line, ">")
	why := law31_line_offence(line)
	msg := sprintf("LAW 31: %s: %s", [why, substring(line, 0, 160)])
}

# The fence case, and it has to inspect the BODY rather than the tag: a tagged ```bash is the
# obvious shape, but the one used on 2026-09-10 was a BARE fence, which no tag-based rule can
# see. A block whose first non-blank line is a command word is an instruction to type it. This is
# the rule that needs the un-blanked fold text -- see the package comment for why it cannot live
# in policy/reply.rego.
fenced_bodies_re := "(?ms)^```[^\\n]*\\n(.*?)^```"

looks_like_command_re := concat("", [
	`^(?:\$\s*)?(?:sudo\s+)?(?:`,
	`bin/[\w.-]+`,
	`|\./\S+|/\S+`,
	`|(?:python3?|pip3?|npm|npx|yarn|pnpm|brew|git|docker|kubectl|helm|flux|make|curl|wget|ssh|bash|sh|zsh|launchctl|systemsetup|gh|uv|uvicorn|pipx|conda|cargo|go|ruby|perl)\b`,
	`|[a-z][a-z0-9]*-(?:install|up|down|deliver|run|build|deploy|bootstrap|start|stop|migrate)\b`,
	`|[a-z][a-z0-9]*(?:-[a-z0-9]+){2,}\b`,
	`)`,
])

fenced_bodies := [m[1] | some m in regex.find_all_string_submatch_n(fenced_bodies_re, input.reply, -1)]

deny contains msg if {
	some body in fenced_bodies
	stripped := trim_space(body)
	stripped != ""
	first := trim_space(split(stripped, "\n")[0])
	regex.match(looks_like_command_re, first)
	msg := sprintf(
		concat("", [
			"LAW 31: the reply hands him a shell block to run: `%s`. A consumer product is installed ",
			"and used; it is not started by a person typing commands.",
		]),
		[substring(first, 0, 110)],
	)
}
