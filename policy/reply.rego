# Refusals that fire on the agent's REPLY to the founder, as data instead of code.
#
# Input (built by opa-hook.py on the Stop event, which decides nothing):
#   input.event  == "Stop"
#   input.reply  the last assistant message above the --- fold, code fences removed
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
	msg := sprintf(concat("", [
		"VIOLATION: Law of Continuous Execution. Do not ask to fix the bug. Fix it and report.\n",
		"  %s\n",
		"Report as: Found X broken. Fixed it in PR Y. Status is now green. ",
		"Reversible work is announced STAGED: with a 60-minute timer, never asked (LAW 48, LAW 49).",
	]), [trim_space(line)])
}
