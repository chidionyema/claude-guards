# Refusals that fire on an agent's TOOL CALL, as data instead of code.
#
# WHY THIS FILE EXISTS
# --------------------
# Two guards were written in Python on 2026-08-24 -- vendor-surface-guard.py
# (146 lines) and adr-sources-guard.py (129 lines) -- and policy.yml refused
# both under the rule in hand_rolled_policy.rego. It was right to. That rule's
# `legacy` list "only ever shrinks", so adding either name would have
# contradicted the list's own contract on the same day it was written, which is
# exactly the reversion the founder named: "this is just chat they wil revet
# back to old habit soon".
#
# So the rules moved here and the two scripts were deleted. What is left on the
# Python side is `opa-hook.py`, an adapter that reads the hook payload and asks
# OPA. It decides nothing, which is why it carries no guard/gate/fence name: the
# whole point of the migration is that the deciding happens in this directory.
#
# THE INPUT
# ---------
# Hook payloads arrive as-is from the harness: `tool_name`, `tool_input`.
# Decision-record checks arrive as `decision_records`, an array built by shell
# and jq in the Makefile, never by a Python collector.
#
#   opa test policy/hooks.rego policy/hooks_test.rego
package hooks

import rego.v1

local_board := "http://127.0.0.1:8787/"

vendor_override := "vendor-surface-intended"

# Artifact actions that only READ. None of them create a surface the founder
# depends on, so none of them are this policy's business.
read_only := {
	"list", "read", "comments", "reply", "resolve", "watch", "unwatch",
	"status", "resume_replies", "list_assets", "read_asset",
}

action := lower(trim_space(input.tool_input.action))

action := "publish" if not input.tool_input.action

haystack := concat(" ", [
	object.get(input, ["tool_input", "description"], ""),
	object.get(input, ["tool_input", "title"], ""),
	object.get(input, ["tool_input", "label"], ""),
	object.get(input, ["tool_input", "file_path"], ""),
])

# ---------------------------------------------------------------------------
# A founder-facing page published to a vendor surface while we serve our own.
#
# 2026-08-24: a session built the board he asked for and published it to
# claude.ai. He opened the link and got a 404. His words: "too nuch frictin, the
# bord os tied to your sessionn, anything we generate bust be persisted in our
# patfron, else iot ends upn the void". board_serve.py was already running on
# 127.0.0.1:8787 under launchd, so the session also built a second board next to
# one that existed (LAW 39).
#
# Reading, listing and replying are allowed. Publishing is what creates the
# surface, so publishing is what this refuses.
deny contains msg if {
	input.tool_name == "Artifact"
	not action in read_only
	not contains(haystack, vendor_override)
	msg := sprintf(concat("", [
		"BLOCKED: this publishes a founder-facing page to claude.ai.\n\n",
		"  He already has a board that does not need you alive to be read:\n",
		"      %s\n",
		"  Built by   ~/.claude/scripts/founder_board.py  (launchd: com.founder.board)\n",
		"  Served by  ~/.claude/scripts/board_serve.py    (launchd: com.founder.boardserve)\n\n",
		"  Add a collector to founder_board.py so the content persists in our own\n",
		"  platform. LAW 34 / R8: no provider single point of failure, Claude included.\n",
		"  LAW 39: the local board already existed.\n\n",
		"  If it genuinely must go outside the estate -- a buyer, an advisor, a\n",
		"  customer -- put  # %s  in the description or title and say why.",
	]), [local_board, vendor_override])
}

# ---------------------------------------------------------------------------
# A decision record that cites nothing.
#
# R18, founder, 2026-08-24: "ok good job but alway research, it pays off all the
# tine". Said right after research reversed a decision already being built: a
# session had started standing up the estate ingress on Traefik's own Docker
# labels, and one search found that SIG Network retired the ingress-nginx
# controller on 2026-03-24 and that Gateway API core is GA at v1.6.0. The real
# decision was the config language, not the vendor.
#
# The class: a decision that binds the platform is recorded without the evidence
# it was based on, so nobody after can tell whether it was researched or guessed.
#
# Not "ADRs must be long". Two dated sources pass. Two rather than one, because
# one source is usually a vendor's own page about itself.
min_sources := 2

deny contains msg if {
	some r in input.decision_records
	not r.has_sources_heading
	msg := sprintf("%s has no '## Sources' heading. A decision record carries the evidence it was made from (R18).", [r.path])
}

deny contains msg if {
	some r in input.decision_records
	r.has_sources_heading
	r.source_urls < min_sources
	msg := sprintf(
		"%s cites %d source URL(s) and needs %d. Two, because one source is usually a vendor's own page about itself (R18).",
		[r.path, r.source_urls, min_sources],
	)
}
