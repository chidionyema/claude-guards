package session_test

import rego.v1

import data.session

# canonical-root-guard's eleven selftest cases, verbatim (crew#603 CP5).

test_canonical_root_itself_and_a_repo_under_it_are_ok if {
	session.cwd_verdict == "ok" with input as {"event": "SessionStart", "cwd": "/Users/x/dev/code", "home": "/Users/x"}
	session.cwd_verdict == "ok" with input as {"event": "SessionStart", "cwd": "/Users/x/dev/code/crew", "home": "/Users/x"}
}

test_other_roots_are_outside if {
	session.cwd_verdict == "outside" with input as {"event": "SessionStart", "cwd": "/Users/x/Documents/code", "home": "/Users/x"}
	session.cwd_verdict == "outside" with input as {"event": "SessionStart", "cwd": "/Users/x/code/Website", "home": "/Users/x"}
	session.cwd_verdict == "outside" with input as {"event": "SessionStart", "cwd": "/Users/x/code-backup/QAlgo", "home": "/Users/x"}
	session.cwd_verdict == "outside" with input as {"event": "SessionStart", "cwd": "/Users/x/Desktop/haworks-platform", "home": "/Users/x"}
	session.cwd_verdict == "outside" with input as {"event": "SessionStart", "cwd": "/Users/x/.hermes/scripts", "home": "/Users/x"} # crew#13: ~/.hermes is retired
	session.cwd_verdict == "outside" with input as {"event": "SessionStart", "cwd": "/Users/x/dev/codex", "home": "/Users/x"} # a sibling that shares the prefix is not under the root
}

test_load_bearing_paths_are_carved_out if {
	session.cwd_verdict == "exempt" with input as {"event": "SessionStart", "cwd": "/Users/x/.claude", "home": "/Users/x"}
	session.cwd_verdict == "exempt" with input as {"event": "SessionStart", "cwd": "/Users/x/.claude/scripts", "home": "/Users/x"}
	session.cwd_verdict == "exempt" with input as {"event": "SessionStart", "cwd": "/Users/x/Documents/code/prospector", "home": "/Users/x"}
	session.cwd_verdict == "exempt" with input as {"event": "SessionStart", "cwd": "/private/tmp/claude-501/x/scratchpad/wt-main", "home": "/Users/x"}
}

test_notice_only_at_session_start_and_only_outside if {
	outside := session.context with input as {"event": "SessionStart", "cwd": "/Users/x/Desktop/haworks-platform", "home": "/Users/x"}
	count({m | some m in outside; startswith(m, "[canonical-root]")}) == 1
	some m in outside
	contains(m, "  cwd    /Users/x/Desktop/haworks-platform")
	inside := session.context with input as {"event": "SessionStart", "cwd": "/Users/x/dev/code/crew", "home": "/Users/x"}
	count({m | some m in inside; startswith(m, "[canonical-root]")}) == 0
	prompt := session.context with input as {"event": "UserPromptSubmit", "cwd": "/Users/x/Desktop", "home": "/Users/x"}
	count({m | some m in prompt; startswith(m, "[canonical-root]")}) == 0
}

test_one_pass_question_is_asked_at_start_and_prompt_not_at_stop if {
	q := data.reply.one_pass_question
	q in session.context with input as {"event": "SessionStart", "cwd": "/Users/x/dev/code", "home": "/Users/x"}
	q in session.context with input as {"event": "UserPromptSubmit", "cwd": "/Users/x/dev/code", "home": "/Users/x"}
	not q in session.context with input as {"event": "Stop", "cwd": "/Users/x/dev/code", "home": "/Users/x"}
}

test_one_active_item_reminder_at_prompt_not_at_start if {
	count({m | some m in session.context with input as {"event": "UserPromptSubmit", "cwd": "/Users/x/dev/code", "home": "/Users/x"}; startswith(m, "[one-active-item]")}) == 1
	count({m | some m in session.context with input as {"event": "SessionStart", "cwd": "/Users/x/dev/code", "home": "/Users/x"}; startswith(m, "[one-active-item]")}) == 0
}
