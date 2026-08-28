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

# crew#331 (LANES rule 2): one lane per session. feed-guard.py passes `holders`, the other
# sessions that wrote on this lane inside the last 2h; each must be named on the OVERLAP line.
deny contains msg if {
	some h in input.holders
	not named_in_overlap(h)
	msg := sprintf("lane %q is held by session %s (handoff inside 2h); name it on the 🔀 OVERLAP line or write on your own lane (crew#331)", [input.lane, h])
}

named_in_overlap(h) if {
	some l in input.lines
	startswith(l, "🔀")
	contains(l, h)
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

# R49-no-secrets-in-chat (founder 2026-08-28: "we dont send password here"): a handoff names WHERE a
# secret is, never WHAT it is. A key word followed by a value is refused; an env NAME in caps is not a value.
secret_line(line) if {
	regex.match(`\b(?i:password|passwd|pass|token|secret|api[_-]?key|private[_-]?key)\b\s*[:=]\s*["']?[^\s"']{8,}`, line)
	not regex.match(`\b(?i:password|passwd|pass|token|secret|api[_-]?key|private[_-]?key)\b\s*[:=]\s*["']?[A-Z][A-Z0-9_]{7,}["']?(\s|$)`, line)
}

deny contains msg if {
	some line in input.lines
	secret_line(line)
	msg := "R49: a handoff never carries a secret value; name where it lives (vault entry, 0600 path), not what it is"
}
