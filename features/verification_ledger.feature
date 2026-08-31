Feature: the record of who measures and who guesses is kept, and it gates promotion
  crew#628 phase 6, founder spec §6. Termination teaches nothing to a process with
  no memory. The penalty is a row, and the consequence of rows is exclusion from
  production work, which is the outcome actually wanted.

  Scenario: a row per session identity over a rolling window
    Given the ledger
    Then it holds, per session identity, the claims made, the claims carrying evidence, the claims refused, the canary windows met, the misses, the passes and the retractions

  Scenario: a contradicted claim is recorded as a retraction
    Given a session asserted a measured result
    And a later probe contradicts it
    Then a retraction is recorded against that session

  Scenario: the founder can read it in one place, sorted by the number that matters
    Given the ledger page
    Then it is one table sorted by misses, highest first
    And a session can read its own row

  Scenario: eligibility is read from the ledger, never asserted by the session
    Given a session is being considered for production work
    When eligibility is decided
    Then it is read from the ledger
    And the session's own account of its record is not consulted

  Scenario: nothing qualifies on the first day
    Given the ledger has just been created and every count is zero
    When eligibility is decided for any session
    Then none qualifies

  Scenario: a miss never terminates a session
    Given a session is recorded as having missed
    Then it is not stopped
    And the only consequence is the row and what the row gates
