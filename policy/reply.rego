# Refusals that fire on the agent's REPLY to the founder, as data instead of code.
#
# Input (built by opa-hook.py on the Stop event, which decides nothing):
#   input.event  == "Stop"
#   input.reply  the last assistant message above the --- fold, code fences removed
#   input.focus  the founder's standing FOCUS: line from ~/.claude/state/goal/FOCUS.json, or ""
#
# LAW 48 (founder, 2026-08-26, crew#280). Session 8f034e1e found the KINI worker down,
# ticketed it and wrote "I stop here since you asked for a status, not a repair; say
# 'fix it' and I start". THE CLASS: a sentence that makes fixing a defect the agent just
# found conditional on the founder's say-so. The deny text is the founder's, verbatim.
#
#   opa test policy/reply.rego policy/reply_test.rego
package reply

import rego.v1

pause_re := `(?i)\bi\s+stop\s+here\b|\bstopp?ing\s+here\s+(?:since|because|as)\s+you\s+asked|\bawaiting\s+(?:your\s+)?(?:permission|go[- ]ahead|approval)\b|\bshould\s+i\s+fix\s+(?:this|it|that)\b|\bsay\s+['"]?fix\s+it['"]?\s+and\s+i\b|\bwant\s+me\s+to\s+fix\s+(?:this|it|that)\b|\bshall\s+i\s+(?:fix|repair|proceed)\b`

deny contains msg if {
	input.event == "Stop"
	some line in split(input.reply, "\n")
	regex.match(pause_re, line)
	msg := sprintf(
		concat("", [
			"VIOLATION: Law of Continuous Execution. Do not ask to fix the bug. Fix it and report.\n",
			"  %s\n",
			"Report as: Found X broken. Fixed it in PR Y. Status is now green. ",
			"Reversible work is announced STAGED: with a 60-minute timer, never asked (LAW 48, LAW 49).",
		]),
		[trim_space(line)],
	)
}

# crew#395 (founder, 2026-08-26: "forget about fly, you have one mission"). A BLOCKED: reply
# whose Need: line asks the founder for a direction is a false blocker while a FOCUS: stands:
# the direction is the focus. A Need: for a hand only he has (a YubiKey tap, a billing
# authorisation) is not a direction and passes. Moved here from dod-guard.py on crew#398.
asks_founder_re := `(?i)\b(founder|him|his)\b`

asks_direction_re := `(?i)\b(decid\w*|decision|direction|priorit\w*|which (?:one|item|ticket|lane|goal)|choose|choice|go-ahead|tell me|say (?:go|which|what)|what to (?:do|work on)|confirm (?:the|which|what) (?:goal|priority|lane|item|ticket))\b`

deny contains msg if {
	input.event == "Stop"
	input.focus != ""
	startswith(trim_space(input.reply), "BLOCKED:")
	some line in split(input.reply, "\n")
	startswith(trim_space(line), "Need:")
	regex.match(asks_founder_re, line)
	regex.match(asks_direction_re, line)
	msg := sprintf(
		concat("", [
			"BLOCKED: asks the founder for a direction he has already given. The standing focus is: %q. ",
			"Work that, or run goal_graph.py --add under it; do not stop for an answer that is on disk.",
		]),
		[substring(input.focus, 0, 160)],
	)
}

# LAW 31 (the founder does not run scripts) and LAW 20 (seamless is the deliverable). crew#431:
# crew#423's enforcement map graded the rule "absent", no guard. THE CLASS: a line above the
# fold that opens with an order aimed at him: run, type, paste, open, click, install. What
# passes: the INVENTORY `Use:` line (one command he may choose to use), `FOUNDER ACTION:`
# (blocker-guard already limits it to physical and billing steps), `STAGED:` (its only ask is
# the word hold), `Expect:`, `Evidence:`, `Open items:`, and everything below the fold. crew#432
# review: "Run 33039029852 filed 0 tickets" and "Copy of the live warehouse" are reports, not
# orders, so the verb alone is not enough: the line must also carry a command (backtick or URL)
# or an object he would act on (the, a, this, your, it).
chore_prefix_re := `(?i)^\s*(?:[-*]\s*)?(?:\*\*)?(?:use|founder action|staged|expect|evidence|open items?):`

chore_re := `(?i)^\s*(?:[-*]\s*|\d+[.)]\s*)?(?:\*\*)?(?:(?:please|then|now|just)\s+)?(?:you(?:'ll| will)? need to\s+|you (?:have|need) to\s+)?(?:run|type|execute|paste|open|click|go to|navigate to|install|copy|tap|ssh into|log in to|login to)\b`

# The verb alone is a report as often as an order. An order also names a command or an object.
chore_object_re := `(?i)\b(?:run|type|execute|paste|open|click|go to|navigate to|install|copy|tap|ssh into|log in to|login to)\s+(?:the|a|an|this|your|it|that|on|into)\b`

chore_command_re := "`|https?://"

is_chore(line) if {
	regex.match(chore_re, line)
	regex.match(chore_object_re, line)
}

is_chore(line) if {
	regex.match(chore_re, line)
	regex.match(chore_command_re, line)
}

deny contains msg if {
	input.event == "Stop"
	some line in split(input.reply, "\n")
	not regex.match(chore_prefix_re, line)
	is_chore(line)
	msg := sprintf(
		concat("", [
			"THE FOUNDER DOES NOT RUN SCRIPTS (LAW 31). This reply hands him a chore:\n",
			"  %s\n",
			"Do it yourself, or make it a scheduled job, a workflow_dispatch, or a STAGED: line. ",
			"A command he may choose to use goes on the INVENTORY Use: line; a physical or billing step is a FOUNDER ACTION: line.",
		]),
		[trim_space(line)],
	)
}

# LAW 4 (think it through, take the smaller road) and hard rule 2 of the headline: "You may not
# hand the founder a menu. Options, trade-off tables and 'say go and I will' are the half-stitched
# habit in its report form. Name the one answer, state the risk in a sentence, and do it." crew#423
# graded the rule take-the-smaller-road-when absent: no guard. THE CLASS: a reply above the fold
# that ends in a choice for him instead of a decision. Four shapes, each one seen in a real reply:
# two or more "Option A / Option B" lines; an "Options:" or "Trade-offs:" header; "say go and I
# will" / "tell me which and I'll"; a "which ... or ... ?" question. What passes: a single real
# question with no alternatives in it ("Which repo should the spec live in?"), STAGED:, and a
# FOUNDER ACTION: naming one word (APPROVE:/DENY: is a decision he owns, not a menu).
menu_option_re := `(?i)^\s*(?:[-*]\s*|\d+[.)]\s*)?(?:\*\*)?option\s+(?:[A-Z]|\d)\b`

menu_header_re := `(?i)^\s*(?:#+\s*)?(?:\*\*)?(?:your\s+)?(?:options?|trade-?offs?|alternatives|choices)(?:\*\*)?\s*:?\s*(?:\*\*)?\s*$`

menu_go_re := `(?i)\b(?:say|reply|tell\s+me|answer)\s+(?:['"\x60]?(?:go|yes|which|a|b|1|2)['"\x60]?)\b.{0,50}\bi(?:'ll|\s+will)\b`

menu_question_re := `(?i)^\s*(?:[-*]\s*)?(?:which|do you (?:want|prefer)|would you (?:like|prefer|rather)|should (?:i|we))\b[^?]*\bor\b[^?]*\?`

menu_line(line) if regex.match(menu_header_re, line)

menu_line(line) if regex.match(menu_go_re, line)

menu_line(line) if regex.match(menu_question_re, line)

deny contains msg if {
	input.event == "Stop"
	some line in split(input.reply, "\n")
	not regex.match(chore_prefix_re, line)
	menu_line(line)
	msg := sprintf(
		concat("", [
			"A MENU IS NOT A DELIVERABLE (LAW 4, headline rule 2). This reply hands the founder a choice:\n",
			"  %s\n",
			"Name the one answer, state the risk in a sentence, and do it. ",
			"Reversible work is STAGED:; only an unsafe or irreversible step is a FOUNDER ACTION: with one word.",
		]),
		[trim_space(line)],
	)
}

# Two Option lines followed by a decision line are a record of the choice, not a menu (code-2f, #132 review).
decision_re := `(?i)^\s*(?:[-*]\s*)?(?:\*\*)?(?:chosen|decision|picked|taking|going with|doing)(?:\*\*)?\s*:`

has_decision if {
	some line in split(input.reply, "\n")
	regex.match(decision_re, line)
}

deny contains msg if {
	input.event == "Stop"
	not has_decision
	options := [line | some line in split(input.reply, "\n"); regex.match(menu_option_re, line)]
	count(options) >= 2
	msg := sprintf(
		"A MENU IS NOT A DELIVERABLE (LAW 4, headline rule 2). %d Option lines above the fold; pick one, state the risk, do it.",
		[count(options)],
	)
}

# LAW 16 (leave a path back when you drop something), crew#423 map row 16 "leave-a-path-back-when":
# the session dropped a thread and wrote no checkpoints/LATEST.md. THE CLASS: a Stop reply that says
# it parks, drops, defers or switches away from an item, on a line that names no way back (a
# checkpoint file, a ticket number, a branch or a "path back:"), while the session's
# checkpoints/LATEST.md is older than 30 minutes or missing. Verbs are matched in lower or sentence
# case only: a live sweep refused a report over the constant DEFER. A park verb needs a thread-like
# object (thread, lane, item, ticket, issue, task, work, ...) or "away from": claude-guards#134 review
# found "Switched to --force-with-lease" and "Dropping the worktree" refused, neither a dropped thread. opa-hook.py supplies
# checkpoint_age_s from the file's mtime; with no value at all the rule stays silent (BLIND, LAW 45).
park_re := `\b(?:[Pp]ark(?:ed|ing)?\s+(?:the\s+|this\s+|that\s+|my\s+|it\s+)?(?:[a-z#\d./-]+\s+){0,3}?(?:thread|lane|item|ticket|issue|task|work|investigation|fix|repair|lead|question|row|checkpoint|cp\d)\b|[Pp]ark(?:ed|ing)?\s+(?:it|this|that)\b|[Dd]ropp(?:ed|ing)\s+(?:the\s+|this\s+|that\s+|my\s+|it\s+)?(?:[a-z#\d./-]+\s+){0,3}?(?:thread|lane|item|ticket|issue|task|work|investigation|fix|repair|lead|question|row|checkpoint|cp\d)\b|[Dd]efer(?:red|ring)?\s+(?:the\s+|this\s+|that\s+|my\s+|it\s+)?(?:[a-z#\d./-]+\s+){0,3}?(?:thread|lane|item|ticket|issue|task|work|investigation|fix|repair|lead|question|row|checkpoint|cp\d)\b|[Ss]helv(?:ed|ing)\s+(?:the\s+|this\s+|that\s+|my\s+|it\s+)?(?:[a-z#\d./-]+\s+){0,3}?(?:thread|lane|item|ticket|issue|task|work|investigation|fix|repair|lead|question|row|checkpoint|cp\d)\b|[Ss]witch(?:ed|ing)\s+away\s+from\b|[Ss]witch(?:ed|ing)\s+to\s+(?:another|a\s+different|the\s+next)\s+(?:thread|lane|item|ticket|issue|task)\b|[Ll]eav(?:e|ing)\s+(?:it|this|that|[a-z#\d]+)\s+for\s+(?:later|now|another)|[Pp]ick(?:ing)?\s+(?:it|this|that|[a-z#\d]+)\s+up\s+later|[Cc]ome\s+back\s+to\s+(?:it|this|that)\s+later)`

path_back_re := `(?i)LATEST\.md|checkpoint|\bpath\s+back\b|#\d+|\b[a-z]+/[a-z0-9._/-]+\b`

park_without_path(line) if {
	regex.match(park_re, line)
	not regex.match(path_back_re, line)
}

deny contains msg if {
	input.event == "Stop"
	input.checkpoint_age_s > 1800
	some line in split(input.reply, "\n")
	park_without_path(line)
	msg := sprintf(
		concat("", [
			"LAW 16: leave a path back when you drop something. This reply parks a thread with no way back on the line:\n",
			"  %s\n",
			"and checkpoints/LATEST.md is %d s old. Name the ticket, branch or checkpoint on that line, ",
			"or write the checkpoint first (map row 16, crew#423).",
		]),
		[trim_space(line), input.checkpoint_age_s],
	)
}

# AGENTS.md hard rule 5 (founder, 2026-08-28: "making excuses you could have fixed in one
# scripted pass without me telling you"). Measured, not graded from prose: opa-hook.py counts
# the turn's edit tool calls (Edit/Write/NotebookEdit, sed -i, python3 - <<, cat >) and the
# distinct files they touched. Six or more edits over three or more files is one-at-a-time
# work by construction; the reply then owes a `Batched:` line naming the pass, or why none.
one_pass_min_edits := 6

one_pass_min_files := 3

one_pass_question := concat("", [
	"[one-pass] AGENTS.md hard rule 5, ONE PASS. Before the first edit ask: can this be batched? ",
	"If several similar fixes are coming (the same lint over N files, the same rename, the same rung ",
	"red in three PRs), write ONE script and run it once; name the pass in one line first. A turn ",
	"that edits 6+ times across 3+ files is refused at Stop unless the reply carries a `Batched:` line.",
])

deny contains msg if {
	input.event == "Stop"
	input.turn_edits >= one_pass_min_edits
	input.turn_files >= one_pass_min_files
	not regex.match(`(?m)^\s*Batched:\s*\S`, input.reply)
	msg := sprintf(
		"[one-pass] this turn made %d separate edits across %d files and the reply has no `Batched:` line. AGENTS.md hard rule 5: similar fixes go in ONE scripted pass. Add `Batched: <the pass you ran, or why these could not be one pass>` and reply again.",
		[input.turn_edits, input.turn_files],
	)
}

# Founder, 2026-08-28: "why is it taking so long" / "how do we prevent doing this same shit again".
# Measured that session: the same fences refused pushes and PR creates four times for paperwork
# (a body-file path, a No-Issue anchor, an evidence image). LAW 38: a guard that refuses correct
# work is an outage. When one hook has refused this session three times in an hour, the reply
# carries a `Guard-tax:` line naming the hook and whether the guard or the work was wrong, so it
# reaches the founder and the science snapshot (hook_outcomes) instead of being absorbed.
guard_tax_threshold := 3

taxed_hooks := {h | some h, n in input.guard_tax; n >= guard_tax_threshold}

deny contains msg if {
	input.event == "Stop"
	count(taxed_hooks) > 0
	not regex.match(`(?m)^\s*Guard-tax:\s*\S`, input.reply)
	msg := sprintf(
		concat("", [
			"BLOCKED by reply.rego (LAW 38, founder 2026-08-28): %s refused this session %d+ times in the last hour. ",
			"A guard that refuses correct work is an outage, and one that is right three times is a worker who is not reading it. ",
			"Add one line: `Guard-tax: <hook> <n> — guard wrong: <why> | work wrong: <why>`. It reaches the founder and hook_outcomes.",
		]),
		[concat(", ", sort(taxed_hooks)), guard_tax_threshold],
	)
}
