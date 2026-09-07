package blocker

import rego.v1

# now is fixed so a row's age is arithmetic, not a clock read.
now := 1000000

physical_row := {"source": "founder-blocker", "outcome": "sent", "key": "physical:touch the key", "msg_id": 40153, "ts": now - 60}

staged_row := {"source": "founder-blocker", "outcome": "staged", "key": "staged:60:merge #252", "msg_id": 40153, "ts": now - 60}

inp(reply, rows) := {"reply": reply, "rows": rows, "now": now, "ledger_readable": true}

test_directive_without_its_receipt_is_refused if {
	count(deny) == 1 with input as inp("FOUNDER ACTION: touch the key", [])
}

test_directive_with_its_receipt_is_permitted if {
	count(deny) == 0 with input as inp("FOUNDER ACTION: touch the key", [physical_row])
}

test_a_staged_receipt_does_not_pay_for_a_physical_directive if {
	count(deny) == 1 with input as inp("FOUNDER ACTION: touch the key", [staged_row])
}

test_staged_with_its_receipt_is_permitted if {
	count(deny) == 0 with input as inp("STAGED: the merge is ready", [staged_row])
}

test_staged_without_its_receipt_is_refused if {
	count(deny) == 1 with input as inp("STAGED: the merge is ready", [])
}

test_both_marks_unpaid_are_two_refusals if {
	count(deny) == 2 with input as inp("FOUNDER ACTION: touch the key\nSTAGED: the merge is ready", [])
}

test_a_receipt_older_than_the_window_does_not_pay if {
	stale := object.union(physical_row, {"ts": now - window_s - 1})
	count(deny) == 1 with input as inp("FOUNDER ACTION: touch the key", [stale])
}

test_a_row_that_never_reached_telegram_does_not_pay if {
	unsent := object.union(physical_row, {"msg_id": 0})
	count(deny) == 1 with input as inp("FOUNDER ACTION: touch the key", [unsent])
}

test_another_sources_row_does_not_pay if {
	other := object.union(physical_row, {"source": "board-deliver"})
	count(deny) == 1 with input as inp("FOUNDER ACTION: touch the key", [other])
}

# The 2026-09-07 refusal: blocker-guard.py blanks code spans before handing the reply over, so the
# self-correction arrives here with nothing left to match. Nothing is asked, nothing is refused.
test_a_mention_survives_as_nothing_and_asks_for_nothing if {
	count(deny) == 0 with input as inp("Correction taken: I wrote   for something that is not a device-in-hand step.", [])
}

test_a_reply_with_no_mark_is_permitted if {
	count(deny) == 0 with input as inp("Merged 8b7a25e0; the tool is on main.", [])
}

# An unreadable ledger cannot prove the message did not land.
test_an_unreadable_ledger_is_blind_not_a_block if {
	blind := object.union(inp("FOUNDER ACTION: touch the key", []), {"ledger_readable": false})
	count(deny) == 0 with input as blind
}
