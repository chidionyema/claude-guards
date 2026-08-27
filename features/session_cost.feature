Feature: Session cost is visible and bounded (crew#26)
  Founder, 2026-08-27: "so how do we solve this, super crucial." Measured that day: $1,375.78 by
  midday, 80% of it context re-sent on every request, 28 compactions in one session.
  Bound to: memory-loop.py --selftest, friction-relay.py --selftest, context-guard-hook.py --selftest,
  test_incident_crew26_hooks_do_not_reinject_resident_text.py

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

  Scenario: Compactions are a counted, strong session signal
    Given a transcript with COMPACT_WARN compaction summaries
    When context-guard assesses the session
    Then it fires strong and names the count
    And one fewer compaction is silent on its own
