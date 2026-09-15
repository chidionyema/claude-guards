package dod

import rego.v1

# The eleven cases dod-guard.py's own `--selftest` carried before this migration (2026-09-15),
# ported verbatim so the Rego rules are proven against the exact texts the Python version was.
inp(reply) := {"reply": reply, "kind": kind} if {
	lines := split(trim_space(reply), "\n")
	count(lines) > 0
	m := regex.find_all_string_submatch_n(`^\**\s*(DONE|INVENTORY|WORKING|WAITING|BLOCKED|STAGED):`, lines[0], 1)
	kind := m[0][1]
} else := {"reply": reply, "kind": ""}

test_done_without_founder_receipt_or_evidence_is_refused if {
	count(deny) == 2 with input as inp("DONE: idp#104 is merged to main as c553b34 and the KINI job has nothing open.\n\nMain CI came back green.")
}

test_inventory_missing_handoff_lines_and_evidence_is_refused if {
	count(deny) == 2 with input as inp("INVENTORY: the worker restarts on merged code.\nBuilt: restart step.\nEvidence: it works.")
}

test_inventory_with_all_five_checkable_lines_is_permitted if {
	count(deny) == 0 with input as inp(concat("\n", [
		"INVENTORY: the ollama-vision alias is on main; you have not tried it yet.",
		"Built: llm/config.yaml now declares `ollama-vision` -> gemma3:4b.",
		"Use: `sb ask --vision <image>` from the menu bar.",
		"Expect: a caption within 10 seconds.",
		"Not done: no founder run yet; pyright has 382 errors.",
		"Evidence: https://github.com/chidionyema/idp/pull/104 merged as c553b34.",
		"",
	]))
}

test_done_with_receipt_and_evidence_is_permitted if {
	count(deny) == 0 with input as inp(concat("\n", [
		"DONE: you ran the vision route and confirmed it.",
		"Founder receipt: crew#219 comment 5414486390, 'works'.",
		"Evidence: https://github.com/chidionyema/idp/pull/104",
		"",
	]))
}

test_working_is_untouched if {
	count(deny) == 0 with input as inp("WORKING: waiting on CI.\n")
}

test_staged_with_its_sentence_and_timer_is_permitted if {
	count(deny) == 0 with input as inp("STAGED: platform/access apply (idp#150) is ready. Reply 'go' to execute immediately, 'hold' to review. Auto-activating in 60 minutes.\n")
}

test_staged_without_its_sentence_or_timer_is_refused if {
	count(deny) == 2 with input as inp("STAGED: platform/access apply is ready, say go.\n")
}

test_live_claim_backed_only_by_a_test_command_is_refused if {
	count(deny) == 1 with input as inp(concat("\n", [
		"INVENTORY: fleetview backend is packaged.",
		"Built: FleetView backend, on cluster and doored.",
		"Use: open the FleetView page in Backstage.",
		"Expect: a live agent roster.",
		"Not done: nothing.",
		"Evidence: `pytest tests/test_fleetview.py` all green.",
		"",
	]))
}

test_live_claim_backed_by_a_running_kube_get_is_permitted if {
	count(deny) == 0 with input as inp(concat("\n", [
		"INVENTORY: fleetview backend is packaged.",
		"Built: FleetView backend, on cluster and doored.",
		"Use: open the FleetView page in Backstage.",
		"Expect: a live agent roster.",
		"Not done: nothing.",
		"Evidence: `idp-kube get deploy fleetview-backend -n backstage` shows 1/1 Running.",
		"",
	]))
}

# DoD v3 final cut: the exact FleetView-fork shape -- a curl the builder ran against its own
# localhost daemon is not independent evidence, however real the response.
test_live_claim_backed_by_a_self_run_curl_is_refused if {
	count(deny) == 1 with input as inp(concat("\n", [
		"DONE: fleetview-backend is deployed and reachable.",
		"Founder receipt: I confirmed it myself.",
		"Evidence: `curl http://127.0.0.1:18790/health` -> 200 OK.",
		"",
	]))
}

test_live_claim_backed_by_qa_agent_is_permitted if {
	count(deny) == 0 with input as inp(concat("\n", [
		"INVENTORY: fleetview backend is packaged.",
		"Built: FleetView backend, on cluster and doored.",
		"Use: open the FleetView page in Backstage.",
		"Expect: a live agent roster.",
		"Not done: nothing.",
		"Evidence: qa-agent ticked the box in `~/.claude/state/qa-agent.json` after a real green run against the cluster deployment.",
		"",
	]))
}

# LAW 31 -- new on this branch (2026-09-15), no Python selftest existed for it before this
# migration, so these cases are new proof rather than a port.
test_law31_naming_an_estate_tool_as_his_action_is_refused if {
	count(deny) == 1 with input as inp("WORKING: still wiring the estate.\nRun bin/idp-bootstrap-estate to finish it.\n")
}

test_law31_asking_him_to_authorise_is_refused if {
	count(deny) == 1 with input as inp("STAGED: policy change ready. Please authorise the change before it lands. Reply 'go' to execute immediately, 'hold' to review. Auto-activating in 30 minutes.\n")
}

# The Use: line is the one place a command he MAY choose to use belongs -- not a chore.
test_law31_a_command_on_the_use_line_is_not_an_offence if {
	count(deny) == 0 with input as inp(concat("\n", [
		"INVENTORY: the deploy is ready.",
		"Built: the deploy script.",
		"Use: run this to apply it.",
		"Expect: it deploys.",
		"Not done: nothing.",
		"Evidence: https://github.com/x/y/pull/1",
		"",
	]))
}

# The 2026-09-10 incident this rule exists for: a BARE fence (no ```bash tag) whose first line
# is a command word.
test_law31_a_bare_fenced_command_block_is_refused if {
	count(deny) == 1 with input as inp("WORKING: packaging the tool.\n\n```\nbin/idp-bootstrap-estate --now\n```\n")
}

test_law31_a_fenced_block_of_prose_is_not_an_offence if {
	count(deny) == 0 with input as inp("WORKING: packaging the tool.\n\n```\nthis is just prose, not a command at all\n```\n")
}

# A command quoted as evidence, inside an Evidence: line, is not work handed over.
test_law31_a_command_inside_evidence_is_not_an_offence if {
	count(deny) == 0 with input as inp(concat("\n", [
		"INVENTORY: the deploy is ready.",
		"Built: the deploy script.",
		"Use: `bin/idp-deploy fleetview`.",
		"Expect: it deploys.",
		"Not done: nothing.",
		"Evidence: ran `bin/idp-deploy fleetview` and it printed OK.",
		"",
	]))
}
