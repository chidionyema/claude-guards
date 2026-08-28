# What runs at SessionStart and UserPromptSubmit, in order. crew#603 CP4 (founder 2026-08-28: "Build ONE door
# (OPA). Every single action the agent takes must pass through hooks.rego").
#
# Before this file, settings/settings.json named seven Python files directly on SessionStart.
# None of them is a refusal: each gathers something (a checkpoint, the founder's complaints,
# the feed, the goal) and injects it as context, or repairs a symlink. Rego cannot read a
# transcript or inject a prompt, so they stay Python -- but which of them run, and in what
# order, is policy, and policy lives here. opa-hook.py asks `data.adapters.session_start`
# and runs each row through hook-run.py (fail-closed: a crashed adapter refuses the start).
#
# A name under scripts/archive/ can never appear here: adapters_test.rego refuses it, and
# hooks.rego refuses the settings.json edit or Bash call that would revive one.
package adapters

import rego.v1

session_start := [
	["sync-guard.py"],
	["laws-link-guard.py"],
	["peer-loop-fence.py"],
	["goal-guard.py"],
	["memory-loop.py"],
	["canonical-root-guard.py"],
	["friction-relay.py"],
	["feed-guard.py", "SessionStart"],
]

# UserPromptSubmit, in order. Same batch rule: five adapters, none a refusal (the one refusal
# in context-guard-hook.py is its PreToolUse half, which settings never wired).
user_prompt_submit := [
	["directive-capture.py"],
	["context-guard-hook.py"],
	["goal-guard.py"],
	["board-deliver.py"],
	["feed-guard.py", "UserPromptSubmit"],
]

# PreToolUse, in order. These eight DO refuse (exit 2 with the reason on stderr, or a JSON
# permissionDecision deny); the door passes the first refusal through untouched and then
# asks hooks.deny. `tools` is the matcher settings.json used to carry; empty means every tool.
# Each is a hand-rolled guard in policy/hand_rolled_policy.rego's ratchet; CP5 moves their
# rules into rego one guard at a time and archives the Python.
pre_tool_use := [
	{"run": ["goal-guard.py"], "tools": []},
	{"run": ["scope-guard.py"], "tools": ["Write", "Edit"]},
	{"run": ["config-syntax-guard.py"], "tools": ["Write", "Edit"]},
	{"run": ["dupe-work-fence.py"], "tools": ["Bash"]},
	{"run": ["pr-cap-guard.py"], "tools": ["Bash"]},
	{"run": ["rule-guard.py"], "tools": ["Bash"]},
	{"run": ["ticket-gate.py"], "tools": ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"]},
	{"run": ["credential-guard.py"], "tools": ["Bash"]},
]

# Stop, in order, after reply.rego. Thirteen adapters; nine refuse (exit 2, or a JSON
# decision=block), four only write (secret-scrub, laws-link-guard, prompt-ledger,
# founder-deliver). The first refusal is the verdict and passes through untouched.
stop := [
	["secret-scrub.py"],
	["laws-link-guard.py"],
	["jargon-guard.py"],
	["vendor-lock-guard.py"],
	["dod-guard.py"],
	["prompt-ledger.py"],
	["repeat-guard.py"],
	["close-guard.py"],
	["founder-deliver.py"],
	["blocker-guard.py"],
	["auto-objective.py"],
	["idle-guard.py"],
	["credential-guard.py"],
	["feed-guard.py", "Stop"],
]
