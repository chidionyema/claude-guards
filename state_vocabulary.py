#!/usr/bin/env python3
"""crew#656 CP0: the state vocabulary, and the banned-token check that enforces it.

Founder spec, 2026-08-29 (requirements: crew docs/requirements/2026-08-29-verification-layer.md;
spec: crew docs/specs/verification-layer.md). His words on the phase: "Phase 0 is the
vocabulary ban and a banned-token check in the broadcast gate. It's an afternoon's work and
it would have caught both of today's failures on its own."

THE TWO FAILURES IT WOULD HAVE CAUGHT, both 2026-08-29:
  ~18:19  a session asserted a CPU-starvation causal chain the evidence did not reach.
  ~21:22  a session told the founder a service was "up" on a peer's self-report. Its own
          probe had reached a redirect at the sign-in door and nothing further.

WHY A TOKEN LIST AND NOT A JUDGEMENT. crew#638's triage: a guard that judges prose or
behaviour has no ground truth, fires on correct work, and cannot be fixed by tuning. This
one is DECLARATIVE -- a rule over a fixed token list, deterministic, and it names the token
it refused so the refusal is actionable rather than mysterious.

WHAT IT DOES NOT DO. It does not judge whether a measurement was good, or whether an
inference over real evidence was sound. The 18:19 failure was a bad inference over real
data; this check only removes the vocabulary that let it be stated as measurement.
Sections 3 to 6 of the spec (prober, envelope, canary, ledger) are the rest, and they are
not this file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# Spec section 2. The only three states anything may assert about a service.
PERMITTED_STATES = ("MEASURED_OK", "MEASURED_FAIL", "UNKNOWN")

# Spec section 2. Banned as assertions about a service.
BANNED = ("up", "down", "healthy", "working", "fine", "operational", "broken")

# A banned token only offends when it is asserted OF a service. "bring the guard back up",
# "the down payment", "a working directory" are ordinary English and must pass, or the check
# becomes a guard that refuses correct work -- an outage, by LAW 38.
#
# The shape that offends: <subject> [is|are|'s|was|were|stays|remains|looks|seems] [not] <token>
# where <subject> ends in something service-shaped. Kept deliberately narrow: a miss is a
# claim that still needs the envelope (spec section 4) to catch it, but a false refusal
# teaches sessions to route around the gate.
_SUBJECTish = r"[A-Za-z][\w.\-/]*"
_COPULA = r"(?:is|are|'s|was|were|stays?|remains?|looks?|seems?|appears?)"
ASSERTION = re.compile(
    rf"\b(?P<subject>{_SUBJECTish})\s+{_COPULA}\s+(?:still\s+|now\s+|not\s+|back\s+)*"
    rf"(?P<token>{'|'.join(BANNED)})\b",
    re.IGNORECASE,
)

# Phrases that use a banned token but assert nothing about a service's state.
EXEMPT = re.compile(
    r"\b(?:"
    r"working (?:directory|tree|copy|day|group|hours?)"
    r"|down (?:payment|time|load|stream)"
    r"|up (?:to date|stream|time)"
    r"|broken (?:link|window|line)"
    r"|operational (?:model|cost|excellence)"
    r"|fine (?:print|grained|tuning|tune)"
    r")\b",
    re.IGNORECASE,
)


class Refusal(Exception):
    """Raised when text asserts service state in banned vocabulary."""


def offending_tokens(text: str) -> list[dict]:
    """Every banned assertion in `text`, each with the token and the phrase that carried it.

    Returns [] for text that asserts nothing about a service. The caller decides what a
    non-empty list means; this function never exits or prints.
    """
    if not text:
        return []
    found = []
    for m in ASSERTION.finditer(text):
        phrase = m.group(0)
        start = max(0, m.start() - 24)
        window = text[start : m.end() + 24]
        if EXEMPT.search(window):
            continue
        found.append(
            {
                "token": m.group("token").lower(),
                "subject": m.group("subject"),
                "phrase": phrase.strip(),
            }
        )
    return found


def check(text: str) -> None:
    """Raise Refusal naming every offending token. The spec requires the token be named."""
    hits = offending_tokens(text)
    if not hits:
        return
    lines = [
        "BLOCKED by state-vocabulary (crew#656 CP0, founder spec section 2):",
        "  a service's state may only be asserted as one of "
        + ", ".join(PERMITTED_STATES)
        + ".",
        "",
    ]
    for h in hits:
        lines.append(f"  refused token: {h['token']!r}   in: {h['phrase']!r}")
    lines += [
        "",
        "  why      'up' and 'down' read as measurements and are not. On 2026-08-29 a",
        "           session told the founder a service was up on a peer's self-report;",
        "           its own probe had reached a redirect at the sign-in door.",
        "  instead  MEASURED_OK  -- a probe inside the freshness window returned the",
        "                          identifier that proves sign-in was passed",
        "           MEASURED_FAIL -- it did not",
        "           UNKNOWN      -- no probe inside the window. This is the default and",
        "                          it is a complete answer, not a failure.",
        "  a peer's report is never evidence. Label it: LEAD (unverified, source: <who>).",
    ]
    raise Refusal("\n".join(lines))


def main() -> int:
    p = argparse.ArgumentParser(description="crew#656 CP0 state-vocabulary check")
    p.add_argument("--text", help="text to check")
    p.add_argument("--file", help="file whose contents to check")
    p.add_argument("--json", action="store_true", help="print findings as JSON, exit 0")
    p.add_argument("--selftest", action="store_true", help="run the built-in cases")
    a = p.parse_args()

    if a.selftest:
        return selftest()

    if a.file:
        with open(a.file, encoding="utf-8") as fh:
            text = fh.read()
    elif a.text is not None:
        text = a.text
    else:
        text = sys.stdin.read()

    if a.json:
        print(json.dumps(offending_tokens(text), indent=2))
        return 0
    try:
        check(text)
    except Refusal as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


REFUSES = [
    "backstage is up",
    "the catalogue is down",
    "langfuse is healthy",
    "the router is working",
    "signoz is fine",
    "the gateway is operational",
    "temporal is broken",
    "Backstage is still up",
    "the catalogue is not down",
    "guacamole is back up",
]

ALLOWS = [
    "backstage is MEASURED_OK",
    "the catalogue is UNKNOWN",
    "the founder asked to bring the feed guard back up for review",
    "a working directory is not a claim",
    "the down payment cleared",
    "keep the operational model in one file",
    "LEAD (unverified, source: code-07): a peer says the catalogue renders",
    'probe_state{service="backstage"} returned 1 forty-two seconds ago',
    "read the fine print",
    "up to date with origin/main",
]


def selftest() -> int:
    bad = []
    for s in REFUSES:
        if not offending_tokens(s):
            bad.append(f"MISSED (should refuse): {s!r}")
    for s in ALLOWS:
        hits = offending_tokens(s)
        if hits:
            bad.append(f"FALSE REFUSAL (should allow): {s!r} -> {hits}")
    for tok in BANNED:
        if not offending_tokens(f"the service is {tok}"):
            bad.append(f"banned token not covered: {tok!r}")
    if bad:
        print("SELFTEST FAILED")
        for b in bad:
            print("  " + b)
        return 1
    print(
        f"selftest ok: {len(REFUSES)} refused, {len(ALLOWS)} allowed, "
        f"all {len(BANNED)} banned tokens covered"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
