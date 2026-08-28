# What runs at SessionStart, in order. crew#603 CP4 (founder 2026-08-28: "Build ONE door
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
	["laws-link-guard.py"],
	["peer-loop-fence.py"],
	["goal-guard.py"],
	["memory-loop.py"],
	["canonical-root-guard.py"],
	["friction-relay.py"],
	["feed-guard.py", "SessionStart"],
]
