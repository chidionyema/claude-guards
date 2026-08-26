package reply

import rego.v1

stop(text) := {"event": "Stop", "reply": text}

test_real_pause_refused if {
	count(deny) == 1 with input as stop("INVENTORY: KINI is merged but not running.\nI stop here since you asked for a status, not a repair; say \"fix it\" and I start on crew#280.")
}

test_should_i_fix_refused if {
	count(deny) == 1 with input as stop("Should I fix this?")
}

test_awaiting_permission_refused if {
	count(deny) == 1 with input as stop("Awaiting permission to touch the plists.")
}

test_fix_report_allowed if {
	count(deny) == 0 with input as stop("Found the KINI worker down. Fixed it in PR idp#151. Status is now green.\nSTAGED: remove the old worktree. Reply 'hold' to cancel. Auto-activating in 60 minutes.")
}

test_scope_question_allowed if {
	count(deny) == 0 with input as stop("Which repo should the spec live in?")
}

test_other_events_ignored if {
	count(deny) == 0 with input as {"event": "PreToolUse", "reply": "I stop here"}
}
