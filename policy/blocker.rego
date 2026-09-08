# LAW 47 / R30, as data instead of code: when a reply may say FOUNDER ACTION: or STAGED:.
#
# A reply carrying either mark is asking the founder for something, and the receipt is a
# founder-blocker.py row in the telegram ledger inside the last hour. Founder, 2026-08-25:
# "again i missed it ... did you send to telegram also? i said it needs to be loud". crew#281
# (2026-08-26) split the two: FOUNDER ACTION: is a physical step, everything else is STAGED:.
#
# The rule these replaced tested `"FOUNDER ACTION:" in reply`, a bare substring, so it also
# refused a reply that only NAMED the mark. It did that on 2026-09-07 to the sentence "I wrote
# `FOUNDER ACTION:` for something that is not a device-in-hand step" -- a reply whose whole
# content was that the mark had been used wrongly, and the only way past it was to stop naming
# the thing being corrected. LAW 38: a guard that refuses correct work is an outage.
#
# So a mark counts when it survives into `input.reply`, which blocker-guard.py hands over with
# fenced blocks dropped and inline code spans blanked. Measured over the 400 most recent
# transcripts -- 43,968 assistant text blocks, 302 naming a mark -- that permits 23 (7.6%), and
# every one read is a mention. Requiring the mark to open a line instead would permit 43
# (14.2%), but most of those are real directives written mid-line after a sentence ("...no
# create-client API. **FOUNDER ACTION:** mint the OAuth client"), so it buys one fixed false
# positive for dozens of false negatives, and a false negative here is a founder blocker that
# reaches nobody.
#
# blocker-guard.py builds the input and asks `data.blocker.deny`. It decides nothing; the rules
# are here and their cases are in blocker_test.rego.
#
#   opa test policy/blocker.rego policy/blocker_test.rego
package blocker

import rego.v1

mark_action := "FOUNDER ACTION:"

mark_staged := "STAGED:"

window_s := 3600

wants_action if contains(input.reply, mark_action)

wants_staged if contains(input.reply, mark_staged)

# A receipt: a founder-blocker row of this outcome, with a real Telegram message id, inside the
# window. `key_prefix` separates the physical row from the staged one; "" matches any key.
receipt(outcome, key_prefix) if {
	some r in input.rows
	r.source == "founder-blocker"
	r.outcome == outcome
	startswith(object.get(r, "key", ""), key_prefix)
	to_number(object.get(r, "msg_id", 0)) > 0
	input.now - to_number(object.get(r, "ts", 0)) <= window_s
}

# BLIND is not a refusal: an unreadable ledger cannot prove the message did NOT land, and a guard
# that blocks on its own blindness stops every reply the moment the ledger file moves.
deny contains msg if {
	input.ledger_readable
	wants_action
	not receipt("sent", "physical:")
	msg := concat("", [
		"BLOCKED by blocker-guard: the reply says FOUNDER ACTION: but no physical founder-blocker ",
		"Telegram message landed in the last 60 minutes (LAW 47 / R30; crew#281: FOUNDER ACTION: ",
		"is for a device in his hand, everything else is STAGED).\n",
		"  physical  python3 ~/.claude/scripts/founder-blocker.py \"<the device step>\" <url-or-word> --physical\n",
		"  else      python3 ~/.claude/scripts/founder-blocker.py \"<action>\" --staged [N]  and write STAGED:\n",
		"  to NAME the mark without asking for anything, write it in `backticks`",
	])
}

deny contains msg if {
	input.ledger_readable
	wants_staged
	not receipt("staged", "")
	msg := concat("", [
		"BLOCKED by blocker-guard: the reply says STAGED: but no staged founder-blocker Telegram ",
		"message landed in the last 60 minutes (crew#281: a staged action he cannot see cannot be held).\n",
		"  run   python3 ~/.claude/scripts/founder-blocker.py \"<action>\" --staged [N]\n",
		"  then  reissue the reply with the STAGED: line it prints\n",
		"  to NAME the mark without asking for anything, write it in `backticks`",
	])
}
