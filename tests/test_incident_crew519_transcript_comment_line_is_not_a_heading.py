"""Incident 2026-08-27 (crew#519): the PR body carried a five-command transcript under
`## Verification evidence`, and `pr-evidence.py check` said "no verification evidence". One
output line inside the fence began `# minus /estate/mcp:` and NEXT_HEADING (`^#{1,4}\\s+\\S`)
took it for the next section heading, cutting the section before the closing fence. Rule:
headings are found with fenced blocks masked; a `#` line inside a fence is transcript."""
import importlib.util
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("pr_evidence", os.path.join(HERE, "pr-evidence.py"))
pe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pe)

TRANSCRIPT = "$ git show origin/main:platform/mcp/agentgateway.yaml | sed -n 2p\n# minus /estate/mcp: estate.db is produced only on the Mac\n$ colima list | tail -1\ndefault    Stopped    x86_64\n"


def _body(section_body: str) -> str:
    return f"intro\n\n## Verification evidence\n{section_body}\n## Definition of done\n1. x\n"


def test_a_hash_line_inside_the_fence_does_not_end_the_section():
    assert pe.transcript_evidence(_body("```\n" + TRANSCRIPT + "```\n")) == 1


def test_a_real_heading_after_the_fence_still_ends_the_section():
    body = _body("```\n" + TRANSCRIPT + "```\n") + "## Later\n```\n" + TRANSCRIPT + "```\n"
    assert pe.transcript_evidence(body) == 1


def test_an_empty_section_is_still_refused():
    assert pe.transcript_evidence(_body("\n")) == 0
