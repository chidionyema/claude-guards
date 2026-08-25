# Ruling numbers are allocated in exactly one place: rulings.json in this repository.
# claude-guards#60 (2026-08-25): R35 and R36 were each claimed by two different founder
# rulings, written first into crew docs, an idp PR body and an issue, while rulings.json
# ended at R33. A number written anywhere else first is the stitch. Two rules:
#   1. no number appears twice in rulings.json;
#   2. every crew docs/rulings/Rnn-*.md file has an Rnn entry in rulings.json.
# Input (built in .github/workflows/policy.yml):
#   {"register": ["R33-feed-handoff-...", ...], "docs": ["R34-net-new-...md", ...]}
package rulings

import rego.v1

number(id) := n if {
	parts := regex.find_n(`^R[0-9]+`, id, 1)
	n := parts[0]
}

register_numbers := {n | some id in input.register; n := number(id)}

deny contains msg if {
	some i, j
	i < j
	number(input.register[i]) == number(input.register[j])
	msg := sprintf("ruling number %s is claimed twice in rulings.json: %s and %s", [number(input.register[i]), input.register[i], input.register[j]])
}

deny contains msg if {
	some f in input.docs
	n := number(f)
	not register_numbers[n]
	msg := sprintf("crew docs/rulings/%s claims %s, which rulings.json does not hold; allocate the number in rulings.json first", [f, n])
}
