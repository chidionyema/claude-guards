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

# --- a markdown file outside the documentation structure (ADR 0002) ----------
write(path) := {"tool_name": "Write", "tool_input": {"file_path": path, "content": "# notes"}}

bash(cmd) := {"tool_name": "Bash", "tool_input": {"command": cmd}}

test_research_dumped_in_the_repo_root_refused if {
	count(hooks.deny) == 1 with input as write("/Users/x/dev/code/idp/RESEARCH-NOTES.md")
}

test_markdown_in_a_random_temp_file_refused if {
	count(hooks.deny) == 1 with input as write("/private/tmp/claude-501/scratch/report.md")
}

test_markdown_under_docs_but_not_a_diataxis_folder_refused if {
	count(hooks.deny) == 1 with input as write("/Users/x/dev/code/idp/docs/prose/thoughts.md")
}

test_refusal_names_the_folders if {
	some msg in hooks.deny with input as write("/Users/x/dev/code/idp/notes.md")
	contains(msg, "docs/explanation/")
	contains(msg, "docs-path-intended")
}

test_edit_of_a_rogue_doc_refused if {
	count(hooks.deny) == 1 with input as {"tool_name": "Edit", "tool_input": {"file_path": "/Users/x/dev/code/crew/PLAN.md", "old_string": "a", "new_string": "b"}}
}

test_heredoc_redirect_into_a_rogue_doc_refused if {
	count(hooks.deny) == 1 with input as bash("cat > /Users/x/dev/code/idp/AUDIT.md <<'EOF'\nhi\nEOF")
}

test_tee_into_a_rogue_doc_refused if {
	count(hooks.deny) == 1 with input as bash("python3 report.py | tee -a findings.md")
}

test_explanation_doc_allowed if {
	count(hooks.deny) == 0 with input as write("/Users/x/dev/code/idp/docs/explanation/why-one-door.md")
}

test_decision_record_allowed if {
	count(hooks.deny) == 0 with input as write("/Users/x/dev/code/idp/docs/decisions/0003-one-door.md")
}

test_mkdocs_home_allowed if {
	count(hooks.deny) == 0 with input as write("/Users/x/dev/code/idp/docs/index.md")
}

test_root_readme_allowed if {
	count(hooks.deny) == 0 with input as write("/Users/x/dev/code/idp/README.md")
}

test_harness_memory_allowed if {
	count(hooks.deny) == 0 with input as write("/Users/x/.claude/projects/p/memory/a-fact.md")
}

test_pr_body_in_temp_allowed if {
	count(hooks.deny) == 0 with input as write("/private/tmp/claude-501/s/pr108-body.md")
}

test_github_template_allowed if {
	count(hooks.deny) == 0 with input as write("/Users/x/dev/code/idp/.github/PULL_REQUEST_TEMPLATE.md")
}

test_non_markdown_write_allowed if {
	count(hooks.deny) == 0 with input as write("/Users/x/dev/code/idp/bin/idp-ci")
}

test_redirect_into_an_allowed_doc_allowed if {
	count(hooks.deny) == 0 with input as bash("python3 gen.py > docs/reference/laws.md")
}

test_redirect_with_override_allowed if {
	count(hooks.deny) == 0 with input as bash("cat > /Users/x/dev/code/idp/NOTES.md  # docs-path-intended: gitignored scratch")
}

test_write_with_override_allowed if {
	count(hooks.deny) == 0 with input as {"tool_name": "Write", "tool_input": {"file_path": "/Users/x/dev/code/idp/NOTES.md", "content": "# docs-path-intended: fixture for a test\n"}}
}

# crew#603 CP4: the archive cannot be revived.
test_running_an_archived_guard_is_refused if {
	count(hooks.deny) > 0 with input as {"tool_name": "Bash", "tool_input": {"command": "python3 $HOME/.claude/scripts/archive/scope-guard.py < in.json"}}
}

test_copying_an_archived_guard_back_is_refused if {
	count(hooks.deny) > 0 with input as {"tool_name": "Bash", "tool_input": {"command": "cd ~/.claude/scripts && cp scripts/archive/scope-guard.py ./scope-guard.py"}}
}

test_reading_the_archive_is_allowed if {
	count(hooks.deny) == 0 with input as {"tool_name": "Bash", "tool_input": {"command": "cat ~/.claude/scripts/archive/scope-guard.py | head -40; git log --oneline -3 -- scripts/archive/"}}
}

test_wiring_an_archived_guard_into_settings_is_refused if {
	count(hooks.deny) > 0 with input as {"tool_name": "Edit", "tool_input": {"file_path": "/Users/x/.claude/scripts/settings/settings.json", "old_string": "opa-hook.py", "new_string": "python3 $HOME/.claude/scripts/archive/scope-guard.py"}}
}

test_a_settings_edit_that_names_no_archive_is_allowed if {
	count(hooks.deny) == 0 with input as {"tool_name": "Edit", "tool_input": {"file_path": "/Users/x/.claude/scripts/settings/settings.json", "old_string": "\"timeout\": 30", "new_string": "\"timeout\": 45"}}
}

# scope-guard, moved from scope-guard.py (crew#603 CP5). The fifteen selftest cases, verbatim.
scope_hits(tool, ti) := count({m | some m in hooks.deny with input as {"tool_name": tool, "tool_input": ti}; contains(m, "into ~/.claude/CLAUDE.md")})

test_scope_bash_heredoc_with_project_token_refused if {
	scope_hits("Bash", {"command": "cat > ~/.claude/CLAUDE.md <<'EOF'\n# graphify\nrun prospector\nEOF"}) == 1
}

test_scope_bash_append_absolute_and_home_refused if {
	scope_hits("Bash", {"command": "echo '# graphify' >> /Users/anyone/.claude/CLAUDE.md"}) == 1
	scope_hits("Bash", {"command": "echo '# graphify' >> $HOME/.claude/CLAUDE.md"}) == 1
}

test_scope_bash_rules_only_read_other_repo_and_escape_pass if {
	scope_hits("Bash", {"command": "cat > ~/.claude/CLAUDE.md <<'EOF'\n# LAW 0\nrules only\nEOF"}) == 0
	scope_hits("Bash", {"command": "cat ~/.claude/CLAUDE.md | rg prospector"}) == 0
	scope_hits("Bash", {"command": "echo prospector >> ~/Documents/code/prospector/CLAUDE.md"}) == 0
	scope_hits("Bash", {"command": "cat > ~/.claude/CLAUDE.md <<'EOF'\nprospector\nEOF\n# SCOPE-LEAK-OK"}) == 0
}

test_scope_write_global_with_token_refused_and_names_it if {
	msgs := {m | some m in hooks.deny with input as {"tool_name": "Write", "tool_input": {"file_path": "/Users/anyone/.claude/CLAUDE.md", "content": "# graphify\nprospector"}}}
	count(msgs) == 1
	some m in msgs
	contains(m, "graphify, prospector")
	scope_hits("Write", {"file_path": "~/.claude/CLAUDE.md", "content": "hermes"}) == 1
	scope_hits("Edit", {"file_path": "$HOME/.claude/CLAUDE.md", "new_string": "see docs/COST_PROGRAM.md"}) == 1
}

test_scope_write_rules_only_escape_project_file_and_read_pass if {
	scope_hits("Write", {"file_path": "/Users/anyone/.claude/CLAUDE.md", "content": "# LAW 0\nrules only"}) == 0
	scope_hits("Write", {"file_path": "/Users/anyone/.claude/CLAUDE.md", "content": "prospector SCOPE-LEAK-OK"}) == 0
	scope_hits("Write", {"file_path": "/Users/anyone/Documents/code/prospector/CLAUDE.md", "content": "prospector runs here"}) == 0
	scope_hits("Edit", {"file_path": "/Users/anyone/.claude/CLAUDE.md", "new_string": "measure before building"}) == 0
	scope_hits("Read", {"file_path": "/Users/anyone/.claude/CLAUDE.md"}) == 0
}
