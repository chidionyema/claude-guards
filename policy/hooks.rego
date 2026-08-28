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
	msg := sprintf(
		concat("", [
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
		]),
		[local_board, vendor_override],
	)
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

# ---------------------------------------------------------------------------
# A markdown file written outside the documentation structure.
#
# Founder, 2026-08-28: "when you ask an agent to do 'research' or 'automate'
# something, they often treat it as a one-off script output rather than
# 'documentation as code.' They dump the results wherever is easiest because
# there is no physical wall stopping them ... If it isn't in the Diátaxis
# structure, the code literally will not commit."
#
# ADR 0002 (idp docs/decisions/0002): documentation is code, Diátaxis is the
# shape, TechDocs renders it. This is the wall. A .md may be written only:
#   - under docs/<tutorials|how-to|reference|explanation|decisions|evidence>/,
#     or as docs/index.md (the mkdocs home);
#   - as one of the root governance files (README, CLAUDE, AGENTS, FOUNDER, ...);
#   - under .github/ (pull request and issue templates are forms, not docs);
#   - under a .claude/ tree (harness memory, checkpoints, laws: not a repo's docs);
#   - in a temp directory when its name ends -body.md (a pull request or issue
#     body handed to `gh --body-file`; that is a message, not a document).
# Everything else is refused, with the folder it belongs in. The same wall
# stands in front of a shell redirect (`> notes.md`, `tee out.md`), because a
# heredoc is how a session dumps a report when Write says no.
# Override: `# docs-path-intended` in the content or the command, with the why.
docs_override := "docs-path-intended"

docs_dirs := `(^|/)docs/(tutorials|how-to|reference|explanation|decisions|evidence)/`

root_docs := {
	"README.md", "CLAUDE.md", "AGENTS.md", "AGENTS-FULL.md", "FOUNDER.md",
	"CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "LICENSE.md",
	"CODE_OF_CONDUCT.md", "SUPPORT.md", "GOVERNANCE.md", "CODEOWNERS.md",
}

basename(path) := p[count(p) - 1] if {
	p := split(path, "/")
}

is_markdown(path) if endswith(lower(path), ".md")

docs_allowed(path) if regex.match(docs_dirs, path)

docs_allowed(path) if regex.match(`(^|/)docs/index.md$`, path)

docs_allowed(path) if basename(path) in root_docs

docs_allowed(path) if contains(path, "/.github/")

docs_allowed(path) if contains(path, "/.claude/")

docs_allowed(path) if {
	regex.match(`^(/private)?/(tmp|var/folders)/`, path)
	endswith(path, "-body.md")
}

rogue_doc(path) if {
	is_markdown(path)
	not docs_allowed(path)
}

docs_reason(path) := sprintf(
	concat("", [
		"BLOCKED: %s is a markdown file outside the documentation structure (ADR 0002, Diátaxis).\n\n",
		"  Put it where a reader will find it and TechDocs will render it:\n",
		"      docs/tutorials/     a lesson, step by step\n",
		"      docs/how-to/        a task, for someone who knows the ground\n",
		"      docs/reference/     facts, tables, data, generated output\n",
		"      docs/explanation/   concepts, research, why it is this way\n",
		"      docs/decisions/     an ADR (MADR shape, ## Sources with two URLs)\n",
		"  and add it to mkdocs.yml nav. Root governance files (README, CLAUDE, AGENTS,\n",
		"  FOUNDER) and a `*-body.md` in a temp dir for `gh --body-file` are allowed.\n\n",
		"  If this file genuinely is not documentation, put  # %s  in it and say why.",
	]),
	[path, docs_override],
)

deny contains msg if {
	input.tool_name in {"Write", "Edit", "MultiEdit"}
	path := object.get(input, ["tool_input", "file_path"], "")
	rogue_doc(path)
	not contains(object.get(input, ["tool_input", "content"], ""), docs_override)
	not contains(object.get(input, ["tool_input", "new_string"], ""), docs_override)
	msg := docs_reason(path)
}

redirect_targets := `(?:>>?|\btee\b(?:\s+-a)?)\s*['"]?([^\s'"|;&<>]+\.md)\b`

deny contains msg if {
	input.tool_name == "Bash"
	cmd := object.get(input, ["tool_input", "command"], "")
	not contains(cmd, docs_override)
	some m in regex.find_all_string_submatch_n(redirect_targets, cmd, -1)
	rogue_doc(m[1])
	msg := docs_reason(m[1])
}

# ---------------------------------------------------------------------------
# crew#603 CP4: an archived guard cannot be revived. Founder, 2026-08-28: "archive
# instead of delete, ensure they cannot be reactivated". A guard whose rules moved
# into this directory goes to scripts/archive/; nothing under that path may be run,
# copied, linked, or written into settings.json again. The archive is for `git log`
# and reading, so plain reads (cat, less, head, sed -n, grep, rg, git log/show, ls,
# diff) are not refused.
archive_path := "scripts/archive/"

revive_verbs := `(^|[\s;&|(])(python3?|bash|sh|zsh|source|exec|cp|mv|ln|chmod|install|rsync)\s+[^\n;&|]*scripts/archive/`

archive_reason(what) := sprintf(
	concat("", [
		"BLOCKED: %s names %s. Those guards were archived under crew#603; their rules live in ",
		"policy/*.rego and opa-hook.py is the one door. Read the archive with cat/git log; ",
		"nothing in it runs, copies, links or gets wired into settings.json again.",
	]),
	[what, archive_path],
)

deny contains msg if {
	input.tool_name == "Bash"
	cmd := object.get(input, ["tool_input", "command"], "")
	regex.match(revive_verbs, cmd)
	msg := archive_reason("this command")
}

deny contains msg if {
	input.tool_name in {"Write", "Edit", "MultiEdit"}
	path := object.get(input, ["tool_input", "file_path"], "")
	endswith(path, "settings.json")
	body := concat("", [
		object.get(input, ["tool_input", "content"], ""),
		object.get(input, ["tool_input", "new_string"], ""),
	])
	contains(body, archive_path)
	msg := archive_reason(path)
}

# crew#603 CP5, batch 1: scope-guard.py, moved here verbatim in rule (2026-08-28). Founder,
# 2026-08-19: "why do we have 2 claude mds, split brain, only one, only critical and useful and
# relevant info." ~/.claude/CLAUDE.md is HOW to work in any repo and is resident in every
# session; a fact about one project written there is billed to all of them. A write that names a
# project token is refused unless the text says SCOPE-LEAK-OK. Reading the file is free.
scope_tokens := `(?i)prospector|hermes|graphify|mumchimp|store_platform|popdd|COST_PROGRAM|PLATFORM_MANIFESTO|WAYS_OF_WORKING|SITE_SPEC_PROGRAM|PACK_NARRATIVE|LAUNCH_OPS|Documents/code/`

scope_escape := "SCOPE-LEAK-OK"

global_rules_path := `^(?:~|\$HOME|/Users/[^/]+)/\.claude/CLAUDE\.md$`

writes_global_rules := `(?:>>?|tee\b[^|;]*|sed\s+-i[^|;]*|cp\b[^|;]*|mv\b[^|;]*)\s*['"]?(?:~|\$HOME|/Users/[^/\s]+)/\.claude/CLAUDE\.md`

scope_body := concat("", [object.get(input.tool_input, "content", ""), object.get(input.tool_input, "new_string", "")])

scope_reason(hits) := sprintf(
	concat("", [
		"REFUSED: this writes %s into ~/.claude/CLAUDE.md.\n",
		"That file is HOW to work, in ANY repo. It is resident in every session in every repo, ",
		"so a fact about one project is billed to all of them and useful to none.\n",
		"Put it in that project's own CLAUDE.md instead, or in a memory file.\n",
		"If the content genuinely belongs in the global rules, add SCOPE-LEAK-OK to say so out loud.",
	]),
	[concat(", ", sort({lower(h) | some h in hits}))],
)

deny contains msg if {
	input.tool_name in {"Write", "Edit", "NotebookEdit"}
	regex.match(global_rules_path, trim_space(input.tool_input.file_path))
	not contains(scope_body, scope_escape)
	hits := regex.find_n(scope_tokens, scope_body, -1)
	count(hits) > 0
	msg := scope_reason(hits)
}

deny contains msg if {
	input.tool_name == "Bash"
	cmd := input.tool_input.command
	not contains(cmd, scope_escape)
	regex.match(writes_global_rules, cmd)
	hits := regex.find_n(scope_tokens, cmd, -1)
	count(hits) > 0
	msg := scope_reason(hits)
}
