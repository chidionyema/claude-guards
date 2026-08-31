Feature: a session cannot assert service state in words that carry no measurement
  crew#628 phase 0, founder spec 2026-08-29 §2. Record:
  ~/.claude/docs/founder/2026-08-29T2213Z-crew-628-verification-layer-4e0f20e1.md
  On 2026-08-29 two sessions asserted live state they had not measured. Phase 0 is
  the vocabulary and the token check. The founder: it would have caught both on its own.

  Scenario: the three permitted states are the only states
    Given a session is describing a service
    Then the only states it may assert are "MEASURED_OK", "MEASURED_FAIL" and "UNKNOWN"

  Scenario: a banned word in an assertion is refused and named
    Given a board post asserting a service is "up"
    When the broadcast gate reads it
    Then the post is refused
    And the refusal names the offending token

  Scenario: every banned token is covered, not just the first
    Given the banned tokens are "up", "down", "healthy", "working", "fine", "operational" and "broken"
    When each is used in turn as an assertion about a service
    Then each one is refused by name

  Scenario: the same word is allowed when it is not an assertion about a service
    Given a post says the founder asked to bring a guard back up for review
    When the broadcast gate reads it
    Then the post is not refused

  Scenario: UNKNOWN is the default and reads as an answer, not a failure
    Given a session has no probe result inside the freshness window
    When it reports the state
    Then it reports "UNKNOWN"
    And the report is accepted without warning
