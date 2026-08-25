# The shape of a 30-minute handoff (R33), as data instead of code.
#
# crew#259 (sync meeting, 2026-08-25): collisions between sessions were found by
# asking each one, not by reading the feed. So every handoff now names what the
# session will change (🔧 TOUCHES:) and which issues another session also touches
# (🔀 OVERLAP:). Both are required; "none" is an answer, empty is not.
#
# feed-guard.py builds {"lines": [...]} and asks `data.feed.deny`. It decides
# nothing; the rules are here and their cases are in feed_test.rego.
#
#   opa test policy/feed.rego policy/feed_test.rego
package feed

import rego.v1

marks := {"🔴", "🟡", "🟢", "⚪", "📍", "🔧", "🔀"}

required := {"🔧 TOUCHES:", "🔀 OVERLAP:"}

max_lines := 8

deny contains msg if {
	count(input.lines) == 0
	msg := "handoff must be 1 to 8 lines, got 0"
}

deny contains msg if {
	count(input.lines) > max_lines
	msg := sprintf("handoff must be 1 to %d lines, got %d", [max_lines, count(input.lines)])
}

deny contains msg if {
	some l in input.lines
	not marked(l)
	msg := sprintf("every line starts with one of 🔴 🟡 🟢 ⚪ 📍 🔧 🔀; refused: %s", [substring(l, 0, 60)])
}

deny contains msg if {
	some r in required
	not present(r)
	msg := sprintf("required line missing or empty (crew#259): %s -- write \"none\" if there is nothing", [r])
}

marked(l) if {
	some m in marks
	startswith(l, m)
}

present(r) if {
	some l in input.lines
	startswith(l, r)
	trim_space(substring(l, count(r), -1)) != ""
}
