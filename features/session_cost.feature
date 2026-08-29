Feature: Session cost is visible and bounded (crew#26)
  Founder, 2026-08-27: "so how do we solve this, super crucial." Measured that day: $1,375.78 by
  midday, 80% of it context re-sent on every request, 28 compactions in one session.
  Bound to: memory-loop.py --selftest, friction-relay.py --selftest,
  test_incident_crew26_hooks_do_not_reinject_resident_text.py
  crew#638 (founder triage, 2026-08-29) removed the third scenario with context-guard-hook: it
  judged whether context was being spent well, which no file records. The cost this feature is
  about is still bounded by the two scenarios that remain -- the laws block and the rulings
  block are the text that was being re-sent, and both are measured in bytes.

  Scenario: The laws block is a pointer, because CLAUDE.md is already in the window
    Given a session start or a compaction
    When memory-loop runs with MEMORY_LOOP_LAWS unset
    Then the [laws] block is under 2 KB and names the ~/AGENTS.md table already in the window
    And MEMORY_LOOP_LAWS=full restores the full copy

  Scenario: Every standing ruling is carried verbatim, its meaning cut to one sentence
    Given rulings.json with 39 rulings
    When friction-relay renders them
    Then every verbatim quote is present
    And the block is under 16 KB
