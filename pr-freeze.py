#!/usr/bin/env python3
"""Refuse to open a NEW pull request while a PR freeze is in force.

Founder directive 2026-08-19, during the queue emergency: "can we lock new prs until this is
resolved". Thirty-one open PRs against an eleven-runner fleet whose python job takes ~26 minutes.
Every merge to main invalidates the other thirty, so each costs a fresh full run: the work grows
pairwise while the pipe stays fixed, and the queue cannot drain. One more PR makes it worse.

Sessions share this estate and cannot see each other, so a note in a doc reaches nobody. This is a
PreToolUse hook, which every session on this machine passes through.

The freeze is a FILE, so the founder turns it off with `rm`, not by editing a script:

    ~/.claude/PR_FREEZE      exists => frozen. Its text is shown to whoever is refused.

What is still allowed while frozen, because none of it adds a branch to the queue:
  - pushing commits, including to the integration branch
  - `gh pr edit`, `gh pr merge`, `gh pr view`, `gh pr list`, `gh pr comment`
  - opening a PR whose head IS the integration branch named in the freeze file
"""
import json
import os
import re
import sys

FREEZE = os.environ.get("PR_FREEZE_PATH") or os.path.expanduser("~/.claude/PR_FREEZE")

# `gh pr create` in any spelling, and the REST call that does the same thing.
CREATE_RE = re.compile(r"\bgh\s+pr\s+create\b")
API_RE = re.compile(r"\bgh\s+api\b.*?\brepos/[^\s]+/pulls\b")
REOPEN_RE = re.compile(r"\bgh\s+pr\s+reopen\b")


def _head_branch(cmd: str) -> str:
    m = re.search(r"--head[= ]+([^\s'\"]+)", cmd)
    return m.group(1) if m else ""


def _allowed_head(text: str) -> str:
    """The branch the freeze file names as the one PR that is still allowed."""
    m = re.search(r"(?im)^\s*Allow-Head:\s*(\S+)", text)
    return m.group(1) if m else ""


def check(cmd: str, freeze: str = "") -> str | None:
    # `freeze` is a parameter only so the selftest can point at a file it controls. Before
    # 2026-08-21 it could not: the selftest called check() with no freeze file on disk, so the
    # guard correctly returned None and three cases "failed". It was grading the guard's OFF
    # state and asserting it was on. The guard was never broken; the test never ran it.
    FREEZE_PATH = freeze or FREEZE
    if not os.path.exists(FREEZE_PATH):
        return None
    if not (CREATE_RE.search(cmd) or API_RE.search(cmd) or REOPEN_RE.search(cmd)):
        return None
    try:
        with open(FREEZE_PATH, encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError:
        text = ""
    allowed = _allowed_head(text)
    if allowed and _head_branch(cmd) == allowed:
        return None
    return (
        "BLOCKED by pr-freeze: new pull requests are frozen.\n"
        + (text or "No reason recorded in ~/.claude/PR_FREEZE.")
        + "\n\nStill allowed: pushing commits, gh pr edit/merge/view/list/comment, and opening a PR"
        + (f" whose --head is {allowed}." if allowed else ".")
        + "\nPut your change on the open integration branch instead of a new PR."
        + f"\nThe founder lifts this with: rm {FREEZE_PATH}"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "")
    message = check(cmd)
    if message is None:
        return 0
    print(message, file=sys.stderr)
    return 2


def selftest() -> int:
    import tempfile

    frozen = [
        ("gh pr create --title x --body y", True),
        ("gh pr create --head integrate/all-open --title x", False),
        ("gh api repos/chidionyema/prospector/pulls -f title=x", True),
        ("gh pr reopen 400", True),
        ("gh pr edit 451 --body-file b.md", False),
        ("gh pr merge 451 --squash", False),
        ("gh pr list --state open", False),
        ("git push origin integrate/all-open", False),
    ]
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "PR_FREEZE")
        with open(path, "w") as fh:
            fh.write("Frozen for the integration run.\nAllow-Head: integrate/all-open\n")
        for cmd, want_block in frozen:
            got = check(cmd, freeze=path) is not None
            if got != want_block:
                print(f"FAIL (frozen) {cmd!r}: blocked={got}, want={want_block}")
                bad += 1

        # The OFF state is the one that runs 99% of the time, and nothing graded it. A guard
        # that blocks when no freeze is declared would stop every session in the estate.
        for cmd, _ in frozen:
            if check(cmd, freeze=os.path.join(d, "no-such-file")) is not None:
                print(f"FAIL (no freeze) {cmd!r}: blocked with no PR_FREEZE on disk")
                bad += 1

        # main(), the hook entry point, end to end over stdin. The mutant that survived on
        # 2026-08-21 flipped `!= "Bash"` to `==`, which makes the guard fire for every tool
        # EXCEPT Bash -- so it would refuse nothing, silently, during a real freeze.
        import json as _json
        import subprocess as _sp
        env = dict(os.environ, PR_FREEZE_PATH=path)
        for payload, want_rc in (
            ({"tool_name": "Bash", "tool_input": {"command": "gh pr create --title x"}}, 2),
            ({"tool_name": "Bash", "tool_input": {"command": "gh pr list"}}, 0),
            ({"tool_name": "Read", "tool_input": {"command": "gh pr create --title x"}}, 0),
            ({"tool_name": "Bash"}, 0),
            ({}, 0),
        ):
            r = _sp.run([sys.executable, os.path.abspath(__file__)], input=_json.dumps(payload),
                        capture_output=True, text=True, env=env, timeout=30)
            if r.returncode != want_rc:
                print(f"FAIL main() on {payload!r}: rc={r.returncode}, want {want_rc}")
                bad += 1
        r = _sp.run([sys.executable, os.path.abspath(__file__)], input="not json",
                    capture_output=True, text=True, env=env, timeout=30)
        if r.returncode != 0:
            print(f"FAIL main() on unparseable stdin: rc={r.returncode}, want 0 (fail open)")
            bad += 1

        # A freeze with no Allow-Head line blocks everything, including the head that would
        # otherwise be exempt. Untested before 2026-08-21.
        bare = os.path.join(d, "BARE")
        with open(bare, "w") as fh:
            fh.write("Frozen, no exemption.\n")
        if check("gh pr create --head integrate/all-open --title x", freeze=bare) is None:
            print("FAIL: a freeze with no Allow-Head exempted a head anyway")
            bad += 1
        msg = check("gh pr create --title x", freeze=bare)
        if not msg or "Frozen, no exemption." not in msg:
            print("FAIL: the refusal did not show the founder's stated reason")
            bad += 1

    print("selftest: " + ("OK" if not bad else f"{bad} failed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
