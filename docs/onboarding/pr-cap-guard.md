# pr-cap-guard: onboarding

**What it is.** A PreToolUse fence on `gh pr create`. If the target repo has more than 20 open PRs the command is refused with the count and the three oldest PRs. Ticket: crew#504 (113 open PRs across seven repos on 2026-08-27; the founder: "we have 24 pull requests open this is crazy").

**What you need to know.**
- Only `gh pr create` is fenced. Merging, closing, reviewing and pushing are never refused by this guard.
- The repo is read from `-R`/`--repo`, else from the checkout's `origin` remote. No repo found: allowed.
- It FAILS OPEN: no `gh`, no network, a non-zero `gh api` exit, an unreadable payload: allowed. It exists to stop a queue growing, not to stop work when GitHub is down.
- The count is a REST call (`gh api repos/O/R/pulls?state=open&per_page=100`), one request per `gh pr create`.

**How to change the cap.** `PR_CAP=<n>` in the session environment; the default is 20 (founder 2026-08-27: "increse the slot to 20"; crew#504 opened at 10).

**How to turn it off.** Remove the `pr-cap-guard.py` entry from the `PreToolUse` hooks in `~/.claude/settings.json` (it sits directly after `dupe-work-fence.py`). `settings/settings.json` in this repo is the tracked copy the install step lays down.

**How to know it is working.** `python3 ~/.claude/scripts/pr-cap-guard.py --selftest` prints nine PASS lines; `tests/test_incident_crew504_pr_cap_refuses_gh_pr_create.py` drives the script through a fake `gh` at 11 and 10 open with `PR_CAP=10`, and at 21 and 20 open with the default.

## Stacked PRs

`gh pr merge N --delete-branch` (or `-d`) is refused while another open PR in the repo has N's head branch as its base. Drop `--delete-branch`, merge, `gh pr edit <stacked> --base main`, and delete the branch once the top of the stack has landed. No gh, or an unknown repo: allow (fail open, like the cap).

## Held PRs

A PR carrying the `hold` label (`PR_CAP_HOLD_LABEL` to rename) is parked, not queued: it pushes nothing and runs nothing, so it does not count toward the cap. The refusal line says so (`label `hold` not counted`).
