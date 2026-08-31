Feature: a claim about live state carries its evidence or it is not written
  crew#628 phase 2, founder spec §4. Prevention at the write beats judgement at
  the read: a schema that refuses a claim without evidence is deterministic,
  and a reviewer who weighs claims is one more thing that can be wrong.

  Scenario: a measured claim with no evidence is refused
    Given a claim stating a measured result
    And the claim carries no evidence
    When the gate reads it
    Then the claim is refused

  Scenario: evidence older than the window downgrades the claim rather than passing it
    Given a claim whose evidence is older than the service's freshness window
    When the gate reads it
    Then the state is rewritten to "UNKNOWN"
    And the author is warned

  Scenario: evidence that returns nothing is not evidence
    Given a claim citing a query that returns no result
    When the gate reads it
    Then the claim is refused

  Scenario: a failed command cannot support a claim that something passed
    Given a claim stating a measured pass
    And its evidence is a command that exited non-zero
    When the gate reads it
    Then the claim is refused

  Scenario: the redirect case is refused by name
    Given a claim stating a measured pass
    And the probe records that the post-sign-in identifier was absent
    When the gate reads it
    Then the claim is refused

  Scenario: a peer session's word is a lead, never evidence
    Given a session has been told by a peer that a service is reachable
    When it repeats that on the board
    Then it must label the statement a lead and name the peer as the source
    And the statement may not carry a measured state

  Scenario: no evidence is permitted only where nothing is being asserted
    Given a claim whose state is "UNKNOWN"
    When the gate reads it
    Then the claim is accepted with no evidence

  Scenario: the gate fails closed on content and loud on its own configuration
    Given the gate cannot reach the metric store
    When a session tries to post a claim
    Then the claim is refused
    And the refusal says the gate is unavailable, distinct from a refused claim
    And at least one channel that does not depend on the gate can report the gate is broken

  Scenario: replies to the founder are covered, not only board posts
    Given a session is replying to the founder and asserting service state
    When the reply is composed
    Then the same evidence rule applies as on the board
