package session

# What a session is told as it starts, decided here and not in Python (crew#603 CP5).
# opa-hook.py queries data.session.context with {"event", "cwd", "home"} and prepends every
# string to the SessionStart / UserPromptSubmit additionalContext. A rule here never blocks:
# it informs. Anything that must refuse belongs in hooks.rego or reply.rego.

import rego.v1

# The one-pass question (hard rule 5) is asked at every start and every prompt.
context contains data.reply.one_pass_question if input.event in {"SessionStart", "UserPromptSubmit"}

# canonical-root-guard.py, ported 2026-08-28. Founder, 2026-08-23: "we should all be working
# from this location and have worktrees and projects littered all over the place ... BROADCAST
# AND GET IT DONE." Measured that day: 67 git checkouts across 6 roots, 12 under ~/dev/code.
# The carve-outs are load-bearing, each reported by the session that owns it on 2026-08-23:
# ~/.claude (the path IS the product; 29 launchd jobs name ~/.claude/scripts), ~/.codex,
# ~/.gemini, ~/Documents/code/prospector (com.chidionyema.reflect hardcodes it), and the
# session scratchpads under /private/tmp/claude-501 and the temp dirs.
# Paths are compared as strings (the Python resolved symlinks); both /tmp and /private/tmp
# are carved out for that reason.
canonical_root := sprintf("%s/dev/code", [input.home])

exempt_roots := {
	sprintf("%s/.claude", [input.home]),
	sprintf("%s/.codex", [input.home]),
	sprintf("%s/.gemini", [input.home]),
	sprintf("%s/Documents/code/prospector", [input.home]),
	"/private/tmp/claude-501",
	"/tmp",
	"/var/folders",
	"/private/var/folders",
}

under(path, parent) if path == parent

under(path, parent) if startswith(path, concat("", [parent, "/"]))

cwd_verdict := "ok" if {
	under(input.cwd, canonical_root)
} else := "exempt" if {
	some e in exempt_roots
	under(input.cwd, e)
} else := "outside"

context contains sprintf(
	concat("", [
		"[canonical-root] This session's cwd is OUTSIDE the canonical root.\n",
		"  cwd    %s\n",
		"  root   %s\n",
		"Founder ruling 2026-08-23: all work happens in %s. Measured that day, 67 git\n",
		"checkouts were spread across 6 roots with only 12 in the root, and two sessions had edited two\n",
		"copies of one repo without either knowing.\n",
		"  - Do not start NEW work here. If this checkout has a twin under the root, use the twin.\n",
		"  - Do not move, delete or `git worktree remove` anything to fix it. One agent owns the\n",
		"    consolidation, and several of these paths are named by launchd jobs that a move would break.\n",
		"  - Push what you are holding. Unpushed commits are the only thing a consolidation cannot\n",
		"    recover.",
	]),
	[input.cwd, canonical_root, canonical_root],
) if {
	input.event == "SessionStart"
	cwd_verdict == "outside"
}

# Founder, 2026-08-28: work slowed because new asks landed inside the running one. LAW 18: every
# founder request is a tracked item; the running one keeps its lane.
context contains concat("", [
	"[one-active-item] If this prompt is a NEW ask while one item is open: put it on the board with an ETA ",
	"in machine-hours and say so in one line (LAW 18); it does not pre-empt the open item unless the founder says now.",
]) if input.event == "UserPromptSubmit"
