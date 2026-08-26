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

asks := "BLOCKED: the board has 138 items.\nTried: the claim list.\nError: none.\nNeed: the founder to decide which item comes first.\nWho: founder.\n"

hand := "BLOCKED: vault seed needs a tap.\nTried: gh workflow run vault-seed.yml.\nError: touch required.\nNeed: a YubiKey tap from the founder.\nWho: founder.\n"

test_blocked_on_a_direction_refused_under_a_focus if {
	count(deny) == 1 with input as {"event": "Stop", "reply": asks, "focus": "crew#284: finish KINI"}
}

test_blocked_on_a_direction_allowed_without_a_focus if {
	count(deny) == 0 with input as {"event": "Stop", "reply": asks, "focus": ""}
}

test_blocked_on_a_physical_hand_allowed_under_a_focus if {
	count(deny) == 0 with input as {"event": "Stop", "reply": hand, "focus": "crew#284: finish KINI"}
}
