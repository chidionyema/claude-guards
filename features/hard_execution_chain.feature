Feature: Hard execution chain (crew#306)
  Founder, 2026-08-26: "You never say 'keep moving' again. The system moves them."
  Bound to: auto-objective.py --selftest, session-timeout.py --selftest, estate_board.py --selftest,
  test_incident_crew306_hard_execution_chain.py

  Scenario: A goalless session is assigned the oldest unclaimed board item
    Given a session stops with no ACTIVE goal
    And the board has open unclaimed items
    When the Stop hook runs
    Then the oldest item is written as the session goal
    And a CLAIM comment is posted on it
    And the stop is refused

  Scenario: An assigned objective with zero progress cannot be walked past
    Given an objective was auto-assigned
    And no state-changing tool call has run since
    When the session stops again
    Then the stop is refused

  Scenario: Progress on disk lets the session end
    Given an objective was auto-assigned
    And a state-changing tool call has run since
    When the session stops
    Then the stop is permitted

  Scenario: A bare BLOCKED is a false blocker
    When the reply starts with BLOCKED: and lacks Tried: Error: Need: or Who:
    Then the stop is refused naming the missing fields
    And false_blocker is on the ledger

  Scenario: A validated BLOCKED is an escape
    When the reply carries BLOCKED: with Tried: Error: Need: Who:
    Then it is posted on the claimed issue
    And the stop is permitted

  Scenario: The retry is graded against the board
    Given a background run is still in flight
    And the agent asks to stop a second time
    And the board has unclaimed items
    Then the stop is refused
    And false_idle is on the ledger

  Scenario: Founder words end it
    When the last user message is STOP or RELEASE
    Then the goal is cleared, the claim released and the stop permitted

  Scenario: A silent session is killed after the grace
    Given a session holds a goal and has written nothing for 10 minutes
    And a process holds its transcript open
    When session-timeout runs in report mode
    Then it prints WOULD KILL and kills nothing
    When session-timeout runs in enforce mode
    Then the process is sent SIGTERM, the goal cleared and the claim released

  Scenario: A board that cannot be read never reads as empty
    When the board is unreadable
    Then every hook permits and writes blind to the ledger

  Scenario: the board is readable from a launchd job
    Given a process whose PATH is /usr/bin:/bin
    When auto-objective --scan asks the board for open items
    Then it resolves gh from a standard install dir and does not print BLIND

  Scenario: a quiet push cannot be reported as pushed
    Given a command containing git push -q or --quiet
    When rule-guard judges it
    Then it is refused unless the command carries quiet-push-intended

  Scenario: a red-alert item with no owner is paged every tick
    Given an open crew item labelled red-alert with no assignee and no CLAIM comment
    When auto-objective --scan runs
    Then it prints RED crew#N and pages the operator, and an owned red-alert item is left alone

  Scenario: estate_board claim writes a CLAIM comment and an unknown subcommand exits 2 (crew#307 incident)
    When a session runs estate_board.py claim N
    Then a comment starting with CLAIM is posted and "CLAIM crew#N posted" is printed
    When a session runs estate_board.py with an unknown subcommand
    Then it exits 2 with usage instead of exiting 0 silently
