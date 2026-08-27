# Refusals that fire on the agent's REPLY to the founder, as data instead of code.
#
# Input (built by opa-hook.py on the Stop event, which decides nothing):
#   input.event  == "Stop"
#   input.reply  the last assistant message above the --- fold, code fences removed
#   input.focus  the founder's standing FOCUS: line from ~/.claude/state/goal/FOCUS.json, or ""
#
# LAW 48 (founder, 2026-08-26, crew#280). Session 8f034e1e found the KINI worker down,
# ticketed it and wrote "I stop here since you asked for a status, not a repair; say
# 'fix it' and I start". THE CLASS: a sentence that makes fixing a defect the agent just
# found conditional on the founder's say-so. The deny text is the founder's, verbatim.
#
#   opa test policy/reply.rego policy/reply_test.rego
package reply

import rego.v1

pause_re := `(?i)\bi\s+stop\s+here\b|\bstopp?ing\s+here\s+(?:since|because|as)\s+you\s+asked|\bawaiting\s+(?:your\s+)?(?:permission|go[- ]ahead|approval)\b|\bshould\s+i\s+fix\s+(?:this|it|that)\b|\bsay\s+['"]?fix\s+it['"]?\s+and\s+i\b|\bwant\s+me\s+to\s+fix\s+(?:this|it|that)\b|\bshall\s+i\s+(?:fix|repair|proceed)\b`

deny contains msg if {
	input.event == "Stop"
	some line in split(input.reply, "\n")
	regex.match(pause_re, line)
	msg := sprintf(
		concat("", [
			"VIOLATION: Law of Continuous Execution. Do not ask to fix the bug. Fix it and report.\n",
			"  %s\n",
			"Report as: Found X broken. Fixed it in PR Y. Status is now green. ",
			"Reversible work is announced STAGED: with a 60-minute timer, never asked (LAW 48, LAW 49).",
		]),
		[trim_space(line)],
	)
}

# crew#395 (founder, 2026-08-26: "forget about fly, you have one mission"). A BLOCKED: reply
# whose Need: line asks the founder for a direction is a false blocker while a FOCUS: stands:
# the direction is the focus. A Need: for a hand only he has (a YubiKey tap, a billing
# authorisation) is not a direction and passes. Moved here from dod-guard.py on crew#398.
asks_founder_re := `(?i)\b(founder|him|his)\b`

asks_direction_re := `(?i)\b(decid\w*|decision|direction|priorit\w*|which (?:one|item|ticket|lane|goal)|choose|choice|go-ahead|tell me|say (?:go|which|what)|what to (?:do|work on)|confirm (?:the|which|what) (?:goal|priority|lane|item|ticket))\b`

deny contains msg if {
	input.event == "Stop"
	input.focus != ""
	startswith(trim_space(input.reply), "BLOCKED:")
	some line in split(input.reply, "\n")
	startswith(trim_space(line), "Need:")
	regex.match(asks_founder_re, line)
	regex.match(asks_direction_re, line)
	msg := sprintf(
		concat("", [
			"BLOCKED: asks the founder for a direction he has already given. The standing focus is: %q. ",
			"Work that, or run goal_graph.py --add under it; do not stop for an answer that is on disk.",
		]),
		[substring(input.focus, 0, 160)],
	)
}

# LAW 31 (the founder does not run scripts) and LAW 20 (seamless is the deliverable). crew#431:
# crew#423's enforcement map graded the rule "absent", no guard. THE CLASS: a line above the
# fold that opens with an order aimed at him: run, type, paste, open, click, install. What
# passes: the INVENTORY `Use:` line (one command he may choose to use), `FOUNDER ACTION:`
# (blocker-guard already limits it to physical and billing steps), `STAGED:` (its only ask is
# the word hold), `Expect:` and `Evidence:`, and everything below the fold.
chore_prefix_re := `(?i)^\s*(?:[-*]\s*)?(?:\*\*)?(?:use|founder action|staged|expect|evidence):`

chore_re := `(?i)^\s*(?:[-*]\s*|\d+[.)]\s*)?(?:\*\*)?(?:(?:please|then|now|just)\s+)?(?:you(?:'ll| will)? need to\s+|you (?:have|need) to\s+)?(?:run|type|execute|paste|open|click|go to|navigate to|install|copy|tap|ssh into|log in to|login to)\b`

deny contains msg if {
	input.event == "Stop"
	some line in split(input.reply, "\n")
	not regex.match(chore_prefix_re, line)
	regex.match(chore_re, line)
	msg := sprintf(
		concat("", [
			"THE FOUNDER DOES NOT RUN SCRIPTS (LAW 31). This reply hands him a chore:\n",
			"  %s\n",
			"Do it yourself, or make it a scheduled job, a workflow_dispatch, or a STAGED: line. ",
			"A command he may choose to use goes on the INVENTORY Use: line; a physical or billing step is a FOUNDER ACTION: line.",
		]),
		[trim_space(line)],
	)
}
