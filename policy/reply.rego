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

# ---------------------------------------------------------------------------------------------
# crew#603 CP5 batch 3: the Stop guards that read only the reply text, moved here from Python.
# input.reply is the last assistant message above the first --- line with code fences blanked
# (opa-hook.last_reply_above_fold). Below the fold is evidence and is never graded.
# ---------------------------------------------------------------------------------------------

# jargon-guard.py (founder 2026-08-20: "not sure wht y of thi neans"; "why dont we avoid jargon
# as law"). Every entry is a word actually used on the founder. Inline code, URLs and paths are
# names, not jargon, and are blanked first. Refuses every time (crew#603: no guard wears down).
jargon := {
	"no-op": "does nothing",
	"idempotent": "safe to run twice",
	"seam": "the place where X plugs in",
	"wire format": "the shape of the data on the network",
	"client-bundled": "code that ships to the browser",
	"source scan": "a test that reads the source",
	"drift test": "a test that fails if the two copies stop matching",
	"path filter": "the rule that decides which tests CI runs",
	"unrefed": "does not hold the process open",
	"unref": "does not hold the process open",
	"fan-out": "run several at once",
	"backpressure": "slowing down when the far end is full",
	"back-pressure": "slowing down when the far end is full",
	"orthogonal": "unrelated",
	"vacuous": "passes without checking anything",
	"blast radius": "how much it breaks",
	"footgun": "easy to get wrong",
	"affordance": "the thing you can click",
	"surface area": "how much of it is exposed",
	"hydrate": "fill in on the browser side",
	"rehydrate": "fill in on the browser side",
	"monotonic": "only ever goes up",
	"hermetic": "runs the same everywhere",
	"memoize": "remember the answer",
	"thunk": "a function you call later",
}

# The shapes the founder corrected by hand (2026-08-2x): opening with what a thing is not,
# giving software a mind, stacking dashes in one line.
jargon_shapes := [
	[`(?i)^\s*(?:DONE|WORKING|BLOCKED)\s*:\s*(?:it'?s|they'?re|that'?s|this is|there'?s|there is)\s+not\b`, "opens by saying what the thing is not", "open with what it is: \"run_v2.py is an ungrounded prototype\""],
	[`(?i)\bthe\s+(?:engine|system|code|pipeline|suite|script|tool|test)\s+(?:exists to|wants|thinks|knows|believes|decides|likes|hates|feels|remembers)\b`, "gives software a mind", "say who did what: \"we built the engine to ...\""],
	[`[^\n]*?(?:\s-{1,2}\s|\s—\s)[^\n]*?(?:\s-{1,2}\s|\s—\s)`, "stacks dashes in one line", "two short sentences instead"],
]

# prose = the reply with inline code, URLs and paths blanked (fences are already gone).
prose := regex.replace(regex.replace(regex.replace(input.reply, "`[^`]*`", " "), `https?://\S+`, " "), `\S*/\S*`, " ")

jargon_hits contains [word, plain] if {
	some word, plain in jargon
	regex.match(sprintf(`(?i)(?:^|[^\w-])%s(?:$|[^\w-])`, [regex_escape(word)]), prose)
}

jargon_hits contains [name, plain] if {
	some [pat, name, plain] in jargon_shapes
	regex.match(pat, prose)
}

regex_escape(s) := regex.replace(s, `([.*+?^${}()|\[\]\\-])`, `\$1`)

deny contains msg if {
	input.event == "Stop"
	count(jargon_hits) > 0
	rows := [sprintf("  \"%s\"  ->  say \"%s\"", [w, p]) | some [w, p] in sort(jargon_hits)]
	msg := concat("\n", array.concat(
		["PLAIN ENGLISH BROKEN IN A REPLY TO THE FOUNDER. He should not have to decode it."],
		array.concat(rows, [
			"",
			"Law: ~/.claude/CLAUDE.md, \"Plain English - say it straight\". His words were \"you sound drunk\" and \"not sure wht y of thi neans\".",
			"Rewrite the text above the --- line and stop again. Below the fold is evidence and is not checked, and anything in backticks is a name, not jargon.",
		]),
	))
}

# dod-guard.py (founder 2026-08-25, Definition of Done v2.1: merged, green and passing are
# inventory, not done). Shape of the claim above the fold; the founder is the oracle for truth.
# The Python's two STAGED sentence checks ("Reply 'go'...", "Auto-activating in N minutes") are
# not ported: R40 (founder 2026-08-27, idp#356) removed the countdown and the approval words.
dod_kind := m[0][1] if {
	first := trim_space(split(trim_space(input.reply), "\n")[0])
	m := regex.find_all_string_submatch_n(`^\s*\**\s*(DONE|INVENTORY|WORKING|WAITING|BLOCKED|STAGED):`, first, 1)
	count(m) > 0
} else := ""

has_line(label) if regex.match(sprintf(`(?im)^\s*(?:[-*\d.]+\s*)?\**\s*%s`, [regex_escape(label)]), input.reply)

checkable := concat("", [`https?://\S+|\b[0-9a-f]{7,40}\b|`, "`[^`]+`", `|(?:~|/)[\w./-]+`])

evidence_is_checkable if {
	some line in split(input.reply, "\n")
	regex.match(`(?i)^\s*(?:[-*\d.]+\s*)?\**\s*Evidence:`, line)
	rest := substring(line, indexof(line, ":") + 1, -1)
	regex.match(checkable, rest)
}

dod_offences contains "DONE: needs a `Founder receipt:` line. If the founder has not used it and confirmed it, the word is INVENTORY:, not DONE:." if {
	dod_kind == "DONE"
	not has_line("Founder receipt:")
}

dod_offences contains "DONE: needs an `Evidence:` line." if {
	dod_kind == "DONE"
	not has_line("Evidence:")
}

dod_offences contains msg if {
	dod_kind == "INVENTORY"
	missing := [h | some h in ["Built:", "Use:", "Expect:", "Not done:", "Evidence:"]; not has_line(h)]
	count(missing) > 0
	msg := sprintf("INVENTORY: needs all five handoff lines; missing %s", [concat(", ", [sprintf("`%s`", [m]) | some m in missing])])
}

dod_offences contains "`Evidence:` must contain a URL, a commit hash, a file path or a `command`." if {
	dod_kind in {"DONE", "INVENTORY"}
	has_line("Evidence:")
	not evidence_is_checkable
}

deny contains msg if {
	input.event == "Stop"
	count(dod_offences) > 0
	msg := concat("\n", array.concat(
		["BLOCKED by dod-guard (Definition of Done v2.1, founder 2026-08-25):"],
		array.concat([sprintf("  - %s", [f]) | some f in sort(dod_offences)], ["  Shape: line 1 DONE:/INVENTORY:/WORKING:/WAITING:/BLOCKED:/STAGED:. INVENTORY carries Built:, Use:, Expect:, Not done:, Evidence:. DONE additionally carries Founder receipt:."]),
	))
}

# vendor-lock-guard.py, Stop face (founder 2026-08-26, crew#182: "the spec is model agnostic";
# LAW 34). A line that names a vendor-only channel AND a word that makes it required, without
# a negation in the same line, commits the founder to one vendor. The --files CI face stays in
# the Python (crew's crew-qa.yml calls it); only the hook moved.
vendor := `(?i)remote[ -]control|claude\s+app|claude\.ai|anthropic\s+(?:app|console|relay)|openai\s+assistants?|chatgpt(?:\s+app)?|gemini\s+live|gemini\s+app|copilot\s+workspace|github\s+copilot\s+chat|cursor\s+(?:app|cloud)|codex\s+(?:app|cloud)|(?:^|[^\w./-])/config\b`

mandate := `(?i)\b(?:turn(?:ed)?\s+on|enable[sd]?|switch(?:ed)?\s+on|activate[sd]?|must|required?|mandatory|only\s+(?:path|way|route)|the\s+path\s+is|step\s+\d|cp\s?\d|done\s+when|you\s+do\s+one\s+thing|only\s+you\s+can)\b`

negated := `(?i)\b(?:off|not|never|no|withdrawn|withdraw|refused|rejected|struck|cancelled|banned|forbidden|cannot|can't|instead\s+of|rather\s+than|why\s+not|versus|vs\.?)\b`

vendor_lock_lines contains [n, trim_space(line)] if {
	some n, line in split(input.reply, "\n")
	regex.match(vendor, line)
	regex.match(mandate, line)
	not regex.match(negated, line)
}

deny contains msg if {
	input.event == "Stop"
	count(vendor_lock_lines) > 0
	msg := concat("\n", array.concat(
		["VENDOR LOCK-IN IN the reply. LAW 34: provider agnostic from day 0, Claude included."],
		array.concat([sprintf("  line %d: %s", [n + 1, substring(l, 0, 160)]) | some [n, l] in sort(vendor_lock_lines)], ["A founder-facing step may not require a channel only one vendor ships. Route it through the estate's own front door (the gateway on Telegram, any runtime over ACP) or mark the vendor feature as off/withdrawn in the same sentence. Founder, 2026-08-26, crew#182."]),
	))
}

# blocker-guard.py (LAW 47 / R30; crew#281). A reply that says FOUNDER ACTION: or STAGED: must
# have reached the founder's Telegram through founder-blocker.py in the last hour. The door
# supplies input.telegram_ledger (rows newer than an hour, source/outcome/key/msg_id) and
# input.ledger_blind when the ledger could not be read (then nothing is checked, and the
# adapter used to say so on stderr; here BLIND permits).
blocker_row(outcome, key_prefix) if {
	some r in input.telegram_ledger
	r.source == "founder-blocker"
	r.outcome == outcome
	startswith(object.get(r, "key", ""), key_prefix)
	to_number(object.get(r, "msg_id", 0)) > 0
}

deny contains msg if {
	input.event == "Stop"
	is_array(input.telegram_ledger) # the door supplies it; BLIND (unreadable ledger) permits
	contains(input.reply, "FOUNDER ACTION:")
	not blocker_row("sent", "physical:")
	msg := concat("\n", [
		"BLOCKED by blocker-guard: the reply says FOUNDER ACTION: but no physical founder-blocker Telegram message landed in the last 60 minutes (LAW 47 / R30; crew#281: FOUNDER ACTION: is for a device in his hand, everything else is STAGED).",
		"  physical  python3 ~/.claude/scripts/founder-blocker.py \"<the device step>\" <url-or-word> --physical",
		"  else      python3 ~/.claude/scripts/founder-blocker.py \"<action>\" --staged [N]  and write STAGED:",
	])
}

deny contains msg if {
	input.event == "Stop"
	is_array(input.telegram_ledger) # the door supplies it; BLIND (unreadable ledger) permits
	contains(input.reply, "STAGED:")
	not blocker_row("staged", "")
	msg := concat("\n", [
		"BLOCKED by blocker-guard: the reply says STAGED: but no staged founder-blocker Telegram message landed in the last 60 minutes (crew#281: a staged action he cannot see cannot be held).",
		"  run   python3 ~/.claude/scripts/founder-blocker.py \"<action>\" --staged [N]",
		"  then  reissue the reply with the STAGED: line it prints",
	])
}
