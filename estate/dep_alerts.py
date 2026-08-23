#!/usr/bin/env python3
"""Read the dependency alerts nobody was reading, and put the count on the board.

WHY THIS IS NOT A CI STEP. It was one, for eleven minutes, and it could never
have worked: GitHub's Actions token cannot read the Dependabot alerts API at
all. Measured 2026-08-23, run 32650836281:

    gh: Resource not accessible by integration (HTTP 403)

`permissions: security-events: read` does not grant it; that scope covers code
scanning. The endpoint wants a token with `security_events`, which the Actions
token is not. A check that can never run is not a guard, it is a red main
branch, so it lives here instead -- on the machine where `gh` is already
authenticated as the founder.

WHY THE BOARD AND NOT A LOG. LAW 28. 36 alerts (27 high, 9 moderate) sat open
on claude-guards while every one of them was five pins in one file. Nothing
turned red, so nothing said they were there. A log file would have been the
same silence with a timestamp. Every session is handed the board at startup,
which makes the board the only place in this estate with a guaranteed reader.

WHAT IT SAYS WHEN IT IS FINE. It posts the green line too, not only the red
one. Alert-on-failure alone teaches a reader that silence means healthy, and
silence is also what this script looks like when it is dead.
"""
import json
import os
import subprocess
import sys

REPOS = ["chidionyema/claude-guards", "chidionyema/claude-estate"]


def alerts(repo):
    """(high_or_critical, moderate_or_low, [worst packages]) or None if unreadable."""
    p = subprocess.run(
        ["gh", "api", f"/repos/{repo}/dependabot/alerts?state=open&per_page=100",
         "-q", '.[] | [.security_advisory.severity, .dependency.package.name] | @tsv'],
        capture_output=True, text=True, timeout=90)
    if p.returncode != 0:
        # Every failure is "unknown", including 404. The first draft read 404 as
        # "alerts are switched off, so there are none", and the negative test
        # below caught what that means: a repository name with a typo in it came
        # back as 0 high, 0 low, clean. A checker that reports a repository it
        # cannot see as healthy is the thing this file exists to stop.
        #
        #   dep_alerts.alerts("chidionyema/definitely-not-a-repo-xyz")
        #   first draft -> (0, 0, [])      reported as clean
        #   now         -> None            reported as unknown
        return None
    hi, lo, names = 0, 0, []
    for line in p.stdout.strip().splitlines():
        sev, _, name = line.partition("\t")
        if sev in ("high", "critical"):
            hi += 1
            if name not in names:
                names.append(name)
        else:
            lo += 1
    return hi, lo, names


def main():
    lines, worst = [], 0
    for repo in REPOS:
        got = alerts(repo)
        if got is None:
            lines.append(f"{repo}: alerts could not be read, so its state is unknown")
            worst = max(worst, 1)
            continue
        hi, lo, names = got
        worst = max(worst, 2 if hi else 0)
        if hi:
            lines.append(f"{repo}: {hi} high or critical and {lo} lower, in "
                         + ", ".join(names[:6]))
        else:
            lines.append(f"{repo}: 0 high or critical, {lo} lower")

    text = ("Dependency alerts. " + " ".join(lines)
            + " Bumping a pin is the whole fix; the last round was 36 alerts in five"
              " packages in one file.")
    print(text)
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import tracked
        tracked.board("dep-alerts" if worst else "dep-alerts-clean", text, "estate")
    except Exception as e:
        print(f"board post failed: {e}", file=sys.stderr)
        return 1
    return 1 if worst == 2 else 0


if __name__ == "__main__":
    sys.exit(main())
