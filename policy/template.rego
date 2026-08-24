# The shape of a command refusal. Copy the marked block into `rules` in
# policy/command.rego, or let `make guard NAME=my_rule` put it there for you.
#
# It is a separate package so that loading policy/ never picks the skeleton up as
# a live rule. Nothing evaluates anything in here.
#
# EVERY FIELD IS REQUIRED, AND THE TWO EXAMPLES ARE THE POINT. `must_match` is a
# command the rule must refuse; `must_not_match` is the nearest command it must
# let through. The `broken` rules in command.rego check every rule against its own
# examples on every evaluation, and `test_no_rule_is_broken` gates that in CI.
#
# That is not paperwork. OPA's regex engine is RE2, which has no lookahead: a
# pattern Python accepted can fail to compile here, and when it does `regex.match`
# is UNDEFINED rather than an error. The rule body then fails, the rule permits
# everything it was written to refuse, and a broken guard prints exactly what a
# clean run prints. The examples are what makes that loud.
#
# Regexes go in backticks, which are raw: no escape processing, and a backtick
# cannot appear inside one.
package command.template

import rego.v1

# >>> entry
entry := {
	"id": "RULE_NAME",
	# RE2. No lookahead -- write the near miss out positively instead.
	"re": `TODO replace this with the pattern that matches the command`,
	# Appending this to the command turns the rule off for that one command.
	# Every rule has an escape, so the guard stops an ACCIDENT and forces intent
	# to be said out loud when it is not one. A rule with no escape gets disabled
	# the first time it is wrong, and then it protects nothing.
	"marker": "RULE_NAME-intended",
	# A command this rule MUST refuse.
	"must_match": "TODO replace this with a command that must be refused",
	# The nearest command it must NOT refuse. A guard that refuses correct work
	# is an outage (LAW 38), so name the near miss you are afraid of.
	"must_not_match": "TODO replace this with the near miss that must go through",
	# What the agent reads when it is stopped. Say what was attempted, why it is
	# wrong in this estate, and what to run instead.
	"msg": concat("", [
		"BLOCKED by rule-guard: TODO what was attempted.\n",
		"TODO why that is a problem here.\n",
		"TODO the command to run instead.",
	]),
}

# <<< entry
