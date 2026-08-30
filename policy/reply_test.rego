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

# crew#431: LAW 31, the founder does not run scripts.
test_chore_line_refused if {
	count(deny) == 1 with input as stop("INVENTORY: the deploy is staged.\nRun `make deploy` and paste the output here.")
}

test_numbered_click_refused if {
	count(deny) == 1 with input as stop("DONE: wired.\n1. Open the console and click Approve.")
}

test_you_need_to_run_refused if {
	count(deny) == 1 with input as stop("INVENTORY: built.\nYou'll need to run `terraform apply` once.")
}

test_format_lines_allowed if {
	count(deny) == 0 with input as stop("INVENTORY: the deploy runs on a schedule now.\nBuilt: a workflow_dispatch deploy.\nUse: `gh workflow run deploy.yml`\nExpect: the run is green in 4 minutes.\nSTAGED: rotating the key. Reply 'hold' to cancel. Auto-activating in 60 minutes.\nFOUNDER ACTION: tap the YubiKey when the phone buzzes.\nThe job runs itself; nothing to run by hand.")
}

test_report_lines_that_start_with_a_verb_allowed if {
	count(deny) == 0 with input as stop("INVENTORY: filed.\nOpen items: crew#12 merge, idp#3 review.\nRun 33039029852 filed 0 tickets.\nCopy of the live warehouse used for the dry run.\nOpen question: which repo.")
}

test_verb_plus_object_refused if {
	count(deny) == 1 with input as stop("DONE: wired.\nOpen the console and approve it.")
}

# LAW 4 / headline rule 2: no menus.
test_option_lines_refused if {
	count(deny) == 1 with input as stop("INVENTORY: two ways to sync the checkout.\nOption A: a launchd job (cheap, Mac-bound).\nOption B: a Dagster row (portable).\nSay which and I start.")
}

test_options_header_refused if {
	count(deny) >= 1 with input as stop("WORKING: the grader is written.\n**Options:**\n- keep the default list\n- read the catalogue")
}

test_say_go_refused if {
	count(deny) >= 1 with input as stop("INVENTORY: the fix is staged on a branch. Say go and I will merge it.")
}

test_which_or_question_refused if {
	count(deny) == 1 with input as stop("Which do you prefer, the Dagster row or the launchd plist?")
}

test_single_option_line_allowed if {
	count(deny) == 0 with input as stop("DONE: took option 2 from the standards page; option A was a table row, not a menu.")
}

test_decision_with_risk_allowed if {
	count(deny) == 0 with input as stop("INVENTORY: the grader reads ESTATE_CHECKOUTS.\nRisk: a checkout absent from the catalogue is not graded; the BLIND row names it.\nSTAGED: remove the launchd copy. Reply 'hold' to cancel. Auto-activating in 60 minutes.")
}

test_founder_word_allowed if {
	count(deny) == 0 with input as stop("BLOCKED: idp#314 waits on the word.\nFOUNDER ACTION: reply APPROVE: healthchecks-row-crew177 or DENY: healthchecks-row-crew177 on https://github.com/chidionyema/idp/pull/314")
}

test_option_lines_with_decision_allowed if {
	count(deny) == 0 with input as stop("INVENTORY: two ways were on the table.\nOption A: launchd.\nOption B: a Dagster row.\nChosen: B, portable; risk: the row needs the daemon up.")
}

# crew#423 row 16: parked thread with no path back, both ways.
stop_aged(text, age) := {"event": "Stop", "reply": text, "checkpoint_age_s": age}

test_parked_thread_without_path_and_stale_checkpoint_refused if {
	count(deny) == 1 with input as stop_aged("INVENTORY: idp row landed.\nParking the drift work for now and switching to the receipt.", 7200)
}

test_parked_thread_with_ticket_on_the_line_allowed if {
	count(deny) == 0 with input as stop_aged("INVENTORY: idp row landed.\nParking the drift work on crew#401 for now, branch fix/crew401-drift.", 7200)
}

test_parked_thread_with_fresh_checkpoint_allowed if {
	count(deny) == 0 with input as stop_aged("Parking the drift work for now and switching to the receipt.", 120)
}

test_no_checkpoint_age_supplied_is_blind_not_a_verdict if {
	count(deny) == 0 with input as stop("Parking the drift work for now and switching to the receipt.")
}

test_dropped_pods_in_a_report_are_not_a_parked_thread if {
	count(deny) == 0 with input as stop_aged("The receipt dropped the two pods that were Succeeded; see checkpoints/LATEST.md.", 7200)
}

test_an_uppercase_constant_is_not_a_parked_thread if {
	count(deny) == 0 with input as stop_aged("The demotion must not set retrieval_failed; that fires DEFER at verify.py:693 and dropped 10 criticals.", 7200)
}

# claude-guards#134 review: two lane shapes that are not a parked thread.
test_switched_to_a_flag_is_not_a_parked_thread if {
	count(deny) == 0 with input as stop_aged("Switched to --force-with-lease after the guard refused the push.", 7200)
}

test_dropping_a_worktree_is_not_a_parked_thread if {
	count(deny) == 0 with input as stop_aged("Dropping the worktree and picking up the next board item.", 7200)
}

test_parking_a_named_lane_without_path_still_refused if {
	count(deny) == 1 with input as stop_aged("Parking the drift lane for now, switching away from it.", 7200)
}

red_estate := {"fresh": true, "document": {"runtime": {
	"clusters": [{"name": "oke", "role": "production", "state": "FAIL", "flux_rows": [{"kind": "Kustomization", "namespace": "flux-system", "name": "tailscale", "ready": false, "message": "stalled"}]}],
	"surfaces": [{"name": "second-hop", "verdict": "FAIL", "detail": "did not load"}],
}}}

ok_estate := {"fresh": true, "document": {"runtime": {"clusters": [{"name": "oke", "role": "production", "state": "OK"}], "surfaces": []}}}

test_green_over_a_red_document_refused if {
	count(deny) == 1 with input as {"event": "Stop", "reply": "DONE: the estate is green and the founder used it", "estate": red_estate}
}

test_refusal_names_the_red_rows if {
	some m in deny with input as {"event": "Stop", "reply": "INVENTORY: all green on the cluster", "estate": red_estate}
	contains(m, "tailscale")
	contains(m, "second-hop")
}

test_green_tests_are_not_a_green_estate if {
	count(deny) == 0 with input as {"event": "Stop", "reply": "INVENTORY: the tests are green; cluster FAIL on tailscale", "estate": red_estate}
}

test_green_over_a_green_document_allowed if {
	count(deny) == 0 with input as {"event": "Stop", "reply": "DONE: the estate is green", "estate": ok_estate}
}

test_a_stale_or_missing_document_refuses_nothing if {
	count(deny) == 0 with input as {"event": "Stop", "reply": "DONE: estate is green", "estate": {"fresh": false}}
	count(deny) == 0 with input as {"event": "Stop", "reply": "DONE: estate is green"}
}
