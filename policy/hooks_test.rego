# Every rule in hooks.rego is one typo away from silently permitting everything.
# Each rule gets a case that must be refused AND a case that must not, because a
# rule only ever seen refusing has never been shown to permit (LAW 38).
package hooks_test

import data.hooks
import rego.v1

artifact(ti) := {"tool_name": "Artifact", "tool_input": ti}

# --- it refuses -------------------------------------------------------------

test_bare_publish_refused if {
	count(hooks.deny) == 1 with input as artifact({"file_path": "/tmp/board.html"})
}

test_explicit_publish_refused if {
	count(hooks.deny) == 1 with input as artifact({"action": "publish", "file_path": "/tmp/b.html"})
}

test_update_of_existing_artifact_refused if {
	count(hooks.deny) == 1 with input as artifact({
		"file_path": "/tmp/b.html",
		"url": "https://claude.ai/code/artifact/x",
	})
}

test_refusal_names_the_local_board if {
	some m in hooks.deny with input as artifact({"file_path": "/tmp/b.html"})
	contains(m, "127.0.0.1:8787")
}

# --- it permits -------------------------------------------------------------

test_read_allowed if {
	count(hooks.deny) == 0 with input as artifact({"action": "read", "url": "u"})
}

test_list_allowed if {
	count(hooks.deny) == 0 with input as artifact({"action": "list"})
}

test_reply_allowed if {
	count(hooks.deny) == 0 with input as artifact({"action": "reply", "url": "u", "thread_id": "t"})
}

test_uppercase_action_still_read_only if {
	count(hooks.deny) == 0 with input as artifact({"action": "READ", "url": "u"})
}

test_override_in_description_allows_publish if {
	count(hooks.deny) == 0 with input as artifact({
		"file_path": "/tmp/b.html",
		"description": "buyer pitch # vendor-surface-intended",
	})
}

test_override_in_title_allows_publish if {
	count(hooks.deny) == 0 with input as artifact({
		"file_path": "/tmp/b.html",
		"title": "Buyer pitch # vendor-surface-intended",
	})
}

test_another_tool_is_not_this_policys_business if {
	count(hooks.deny) == 0 with input as {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x"}}
}

# --- decision records, both ways --------------------------------------------

record(p, h, n) := {"path": p, "has_sources_heading": h, "source_urls": n}

test_record_with_no_heading_refused if {
	count(hooks.deny) == 1 with input as {"decision_records": [record("a.md", false, 9)]}
}

test_record_with_heading_and_no_urls_refused if {
	count(hooks.deny) == 1 with input as {"decision_records": [record("a.md", true, 0)]}
}

test_record_with_one_url_refused if {
	count(hooks.deny) == 1 with input as {"decision_records": [record("a.md", true, 1)]}
}

test_record_with_two_urls_permitted if {
	count(hooks.deny) == 0 with input as {"decision_records": [record("a.md", true, 2)]}
}

test_each_bad_record_is_named_once if {
	count(hooks.deny) == 3 with input as {"decision_records": [
		record("a.md", false, 0),
		record("b.md", true, 1),
		record("c.md", true, 2),
		record("d.md", true, 7),
		record("e.md", false, 3),
	]}
}

test_no_records_is_not_a_refusal if {
	count(hooks.deny) == 0 with input as {"decision_records": []}
}
