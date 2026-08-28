package reply

import rego.v1

stop(text) := {"event": "Stop", "reply": text}

# The menu/pause/chore rules are graded on their own; the ported dod, jargon, vendor and blocker
# rules (crew#603 CP5 batch 3) have their own tests below and are filtered out here.
own(set) := {m | some m in set; not startswith(m, "BLOCKED by dod-guard"); not startswith(m, "PLAIN ENGLISH"); not startswith(m, "VENDOR LOCK-IN"); not startswith(m, "BLOCKED by blocker-guard")}

test_real_pause_refused if {
	count(own(deny)) == 1 with input as stop("INVENTORY: KINI is merged but not running.\nI stop here since you asked for a status, not a repair; say \"fix it\" and I start on crew#280.")
}

test_should_i_fix_refused if {
	count(own(deny)) == 1 with input as stop("Should I fix this?")
}

test_awaiting_permission_refused if {
	count(own(deny)) == 1 with input as stop("Awaiting permission to touch the plists.")
}

test_fix_report_allowed if {
	count(own(deny)) == 0 with input as stop("Found the KINI worker down. Fixed it in PR idp#151. Status is now green.\nSTAGED: remove the old worktree. Reply 'hold' to cancel. Auto-activating in 60 minutes.")
}

test_scope_question_allowed if {
	count(own(deny)) == 0 with input as stop("Which repo should the spec live in?")
}

test_other_events_ignored if {
	count(own(deny)) == 0 with input as {"event": "PreToolUse", "reply": "I stop here"}
}

asks := "BLOCKED: the board has 138 items.\nTried: the claim list.\nError: none.\nNeed: the founder to decide which item comes first.\nWho: founder.\n"

hand := "BLOCKED: vault seed needs a tap.\nTried: gh workflow run vault-seed.yml.\nError: touch required.\nNeed: a YubiKey tap from the founder.\nWho: founder.\n"

test_blocked_on_a_direction_refused_under_a_focus if {
	count(own(deny)) == 1 with input as {"event": "Stop", "reply": asks, "focus": "crew#284: finish KINI"}
}

test_blocked_on_a_direction_allowed_without_a_focus if {
	count(own(deny)) == 0 with input as {"event": "Stop", "reply": asks, "focus": ""}
}

test_blocked_on_a_physical_hand_allowed_under_a_focus if {
	count(own(deny)) == 0 with input as {"event": "Stop", "reply": hand, "focus": "crew#284: finish KINI"}
}

# crew#431: LAW 31, the founder does not run scripts.
test_chore_line_refused if {
	count(own(deny)) == 1 with input as stop("INVENTORY: the deploy is staged.\nRun `make deploy` and paste the output here.")
}

test_numbered_click_refused if {
	count(own(deny)) == 1 with input as stop("DONE: wired.\n1. Open the console and click Approve.")
}

test_you_need_to_run_refused if {
	count(own(deny)) == 1 with input as stop("INVENTORY: built.\nYou'll need to run `terraform apply` once.")
}

test_format_lines_allowed if {
	count(own(deny)) == 0 with input as stop("INVENTORY: the deploy runs on a schedule now.\nBuilt: a workflow_dispatch deploy.\nUse: `gh workflow run deploy.yml`\nExpect: the run is green in 4 minutes.\nSTAGED: rotating the key. Reply 'hold' to cancel. Auto-activating in 60 minutes.\nFOUNDER ACTION: tap the YubiKey when the phone buzzes.\nThe job runs itself; nothing to run by hand.")
}

test_report_lines_that_start_with_a_verb_allowed if {
	count(own(deny)) == 0 with input as stop("INVENTORY: filed.\nOpen items: crew#12 merge, idp#3 review.\nRun 33039029852 filed 0 tickets.\nCopy of the live warehouse used for the dry run.\nOpen question: which repo.")
}

test_verb_plus_object_refused if {
	count(own(deny)) == 1 with input as stop("DONE: wired.\nOpen the console and approve it.")
}

# LAW 4 / headline rule 2: no menus.
test_option_lines_refused if {
	count(own(deny)) == 1 with input as stop("INVENTORY: two ways to sync the checkout.\nOption A: a launchd job (cheap, Mac-bound).\nOption B: a Dagster row (portable).\nSay which and I start.")
}

test_options_header_refused if {
	count(deny) >= 1 with input as stop("WORKING: the grader is written.\n**Options:**\n- keep the default list\n- read the catalogue")
}

test_say_go_refused if {
	count(deny) >= 1 with input as stop("INVENTORY: the fix is staged on a branch. Say go and I will merge it.")
}

test_which_or_question_refused if {
	count(own(deny)) == 1 with input as stop("Which do you prefer, the Dagster row or the launchd plist?")
}

test_single_option_line_allowed if {
	count(own(deny)) == 0 with input as stop("DONE: took option 2 from the standards page; option A was a table row, not a menu.")
}

test_decision_with_risk_allowed if {
	count(own(deny)) == 0 with input as stop("INVENTORY: the grader reads ESTATE_CHECKOUTS.\nRisk: a checkout absent from the catalogue is not graded; the BLIND row names it.\nSTAGED: remove the launchd copy. Reply 'hold' to cancel. Auto-activating in 60 minutes.")
}

test_founder_word_allowed if {
	count(own(deny)) == 0 with input as stop("BLOCKED: idp#314 waits on the word.\nFOUNDER ACTION: reply APPROVE: healthchecks-row-crew177 or DENY: healthchecks-row-crew177 on https://github.com/chidionyema/idp/pull/314")
}

test_option_lines_with_decision_allowed if {
	count(own(deny)) == 0 with input as stop("INVENTORY: two ways were on the table.\nOption A: launchd.\nOption B: a Dagster row.\nChosen: B, portable; risk: the row needs the daemon up.")
}

# crew#423 row 16: parked thread with no path back, both ways.
stop_aged(text, age) := {"event": "Stop", "reply": text, "checkpoint_age_s": age}

test_parked_thread_without_path_and_stale_checkpoint_refused if {
	count(own(deny)) == 1 with input as stop_aged("INVENTORY: idp row landed.\nParking the drift work for now and switching to the receipt.", 7200)
}

test_parked_thread_with_ticket_on_the_line_allowed if {
	count(own(deny)) == 0 with input as stop_aged("INVENTORY: idp row landed.\nParking the drift work on crew#401 for now, branch fix/crew401-drift.", 7200)
}

test_parked_thread_with_fresh_checkpoint_allowed if {
	count(own(deny)) == 0 with input as stop_aged("Parking the drift work for now and switching to the receipt.", 120)
}

test_no_checkpoint_age_supplied_is_blind_not_a_verdict if {
	count(own(deny)) == 0 with input as stop("Parking the drift work for now and switching to the receipt.")
}

test_dropped_pods_in_a_report_are_not_a_parked_thread if {
	count(own(deny)) == 0 with input as stop_aged("The receipt dropped the two pods that were Succeeded; see checkpoints/LATEST.md.", 7200)
}

test_an_uppercase_constant_is_not_a_parked_thread if {
	count(own(deny)) == 0 with input as stop_aged("The demotion must not set retrieval_failed; that fires DEFER at verify.py:693 and dropped 10 criticals.", 7200)
}

# claude-guards#134 review: two lane shapes that are not a parked thread.
test_switched_to_a_flag_is_not_a_parked_thread if {
	count(own(deny)) == 0 with input as stop_aged("Switched to --force-with-lease after the guard refused the push.", 7200)
}

test_dropping_a_worktree_is_not_a_parked_thread if {
	count(own(deny)) == 0 with input as stop_aged("Dropping the worktree and picking up the next board item.", 7200)
}

test_parking_a_named_lane_without_path_still_refused if {
	count(own(deny)) == 1 with input as stop_aged("Parking the drift lane for now, switching away from it.", 7200)
}

test_one_pass_six_edits_three_files_no_batched_line_refused if {
	count(data.reply.deny) > 0 with input as {"event": "Stop", "reply": "INVENTORY: x", "turn_edits": 6, "turn_files": 3}
}

test_one_pass_batched_line_passes if {
	count({m | some m in data.reply.deny; contains(m, "[one-pass]")}) == 0 with input as {"event": "Stop", "reply": "INVENTORY: x\nBatched: one ruff --fix pass over 22 files", "turn_edits": 9, "turn_files": 9}
}

test_one_pass_iterating_one_file_passes if {
	count({m | some m in data.reply.deny; contains(m, "[one-pass]")}) == 0 with input as {"event": "Stop", "reply": "INVENTORY: x", "turn_edits": 9, "turn_files": 1}
}

# ---- crew#603 CP5 batch 3: the four Stop text rules, cases carried over from each selftest ----

jargon_msgs(text) := {m | some m in deny with input as stop(text); startswith(m, "PLAIN ENGLISH")}

test_jargon_blocks_the_real_reply if {
	got := {w | some [w, _] in jargon_hits} with input as stop("Three things worth a reviewer's eye: the client-bundled module never sees the key, a source scan proves it, and the drift test is single-lane because of the CI path filter. The timer is unrefed.")
	got == {"client-bundled", "source scan", "drift test", "path filter", "unrefed"}
}

test_jargon_passes_the_rewrite_code_paths_and_longer_words if {
	count(jargon_msgs("Three things worth a reviewer's eye: the browser never gets the key, a test reads the source and fails if anything imports it, and the copy check only runs in one of the two apps. The timer does not hold the build open.")) == 0
	count(jargon_msgs("The `no-op` flag is set.")) == 0
	count(jargon_msgs("See src/seam/thunk.ts for it.")) == 0
	count(jargon_msgs("The seamstress arrived.")) == 0
	count(jargon_msgs("A no-operation call.")) == 0
}

test_jargon_report_names_the_word_and_the_plain_form if {
	msgs := jargon_msgs("This is idempotent.")
	count(msgs) == 1
	some m in msgs
	contains(m, "\"idempotent\"  ->  say \"safe to run twice\"")
}

test_jargon_shapes_he_corrected if {
	got := {w | some [w, _] in jargon_hits} with input as stop("DONE: they're not two versions of the same thing. `run.py` is the engine. `run_v2.py` is an ungrounded prototype of the moat - the thing the engine exists to not be.")
	got == {"opens by saying what the thing is not", "gives software a mind"}
	count(jargon_msgs("DONE: `run.py` is the engine and `run_v2.py` is an ungrounded prototype. We built the engine to ground every claim in retrieval. The prototype retrieves nothing.")) == 0
	[w | some [w, _] in jargon_hits] == ["stacks dashes in one line"] with input as stop("DONE: the fix landed - the gate is green - we can ship.")
	count(jargon_msgs("DONE: the fix landed - the gate is green.")) == 0
	count(jargon_msgs("DONE: the scheduler is not running yet.")) == 0
}

dod_msgs(text) := {m | some m in deny with input as stop(text); startswith(m, "BLOCKED by dod-guard")}

test_dod_done_without_receipt_refused if {
	msgs := dod_msgs("DONE: idp#104 is merged to main as c553b34 and the KINI job has nothing open.\n\nMain CI came back green.")
	count(msgs) == 1
	some m in msgs
	contains(m, "Founder receipt:")
}

test_dod_inventory_missing_lines_and_prose_evidence_refused if {
	msgs := dod_msgs("INVENTORY: the worker restarts on merged code.\nBuilt: restart step.\nEvidence: it works.")
	count(msgs) == 1
	some m in msgs
	contains(m, "Use:")
	contains(m, "must contain a URL, a commit hash, a file path or a `command`")
}

test_dod_complete_shapes_allowed if {
	count(dod_msgs("INVENTORY: the ollama-vision alias is on main; you have not tried it yet.\nBuilt: llm/config.yaml now declares `ollama-vision` -> gemma3:4b.\nUse: `sb ask --vision <image>` from the menu bar.\nExpect: a caption within 10 seconds.\nNot done: no founder run yet; pyright has 382 errors.\nEvidence: https://github.com/chidionyema/idp/pull/104 merged as c553b34.\n")) == 0
	count(dod_msgs("DONE: you ran the vision route and confirmed it.\nFounder receipt: crew#219 comment 5414486390, 'works'.\nEvidence: https://github.com/chidionyema/idp/pull/104\n")) == 0
	count(dod_msgs("WORKING: waiting on CI.\n")) == 0
	count(dod_msgs("STAGED: platform/access apply (idp#150) is ready.\n")) == 0
}

vendor_msgs(text) := {m | some m in deny with input as stop(text); startswith(m, "VENDOR LOCK-IN")}

test_vendor_lock_real_reply_refused_and_names_the_line if {
	msgs := vendor_msgs("INVENTORY: nothing is broken.\nUse: in Claude Code run `/config`, turn on \"Remote Control for all sessions\", and turn on push notifications in the Claude app on your phone. That is step 1 and only you can do it.\n")
	count(msgs) == 1
	some m in msgs
	contains(m, "line 2:")
}

test_vendor_lock_negated_plain_mention_and_bare_mandate_allowed if {
	count(vendor_msgs("- **Remote Control** — off. Not a fallback, not a step.\n| Anthropic Remote Control | Claude only; needs claude.ai login; no API key (LAW 34). |\n**v2 is withdrawn.** It turned on Anthropic Remote Control for one vendor's sessions.\nStep 1: the phone sends a Telegram message to the gateway; done when the draft comes back.\n")) == 0
	count(vendor_msgs("Claude Code is installed at 0.65.0.")) == 0
	count(vendor_msgs("Step 1 must be done first.")) == 0
}

stop_ledger(text, rows) := {"event": "Stop", "reply": text, "telegram_ledger": rows}

blocker_msgs(text, rows) := {m | some m in deny with input as stop_ledger(text, rows); startswith(m, "BLOCKED by blocker-guard")}

sent_physical := [{"source": "founder-blocker", "outcome": "sent", "key": "physical:oci-login", "msg_id": 18378}]

staged_row := [{"source": "founder-blocker", "outcome": "staged", "key": "staged:apply", "msg_id": 18379}]

test_blocker_founder_action_without_a_physical_row_refused if {
	count(blocker_msgs("BLOCKED: OCI login.\nFOUNDER ACTION: open https://x/login on your phone.", [])) == 1
	count(blocker_msgs("BLOCKED: OCI login.\nFOUNDER ACTION: open https://x/login on your phone.", staged_row)) == 1
	count(blocker_msgs("BLOCKED: OCI login.\nFOUNDER ACTION: open https://x/login on your phone.", sent_physical)) == 0
}

test_blocker_staged_without_a_staged_row_refused if {
	count(blocker_msgs("STAGED: platform/access apply is ready.", [])) == 1
	count(blocker_msgs("STAGED: platform/access apply is ready.", sent_physical)) == 1
	count(blocker_msgs("STAGED: platform/access apply is ready.", staged_row)) == 0
}

test_blocker_blind_ledger_permits_and_a_plain_reply_is_not_checked if {
	count({m | some m in deny with input as stop("FOUNDER ACTION: open https://x/login on your phone."); startswith(m, "BLOCKED by blocker-guard")}) == 0
	count(blocker_msgs("WORKING: nothing for you.", [])) == 0
}
