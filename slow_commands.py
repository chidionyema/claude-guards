#!/usr/bin/env python3
"""Tell a session when it is about to block on a command that has always been slow.

Founder, 2026-09-07, watching a peer session sit still for 2m29s on `trivy config`:
"like this the waits, the slience,s a lot of tine is spent waiting".

MEASURED, over 14,176 paired tool calls in this project's transcripts (the one 12.3h outlier
dropped, it is a dead session rather than a command):

    calls >= 30s     667  ( 4.7% of calls)   26.46h  = 69.4% of all tool wait
    calls >= 60s     313  ( 2.2%)            22.29h  = 58.5%
    calls >=120s      88  ( 0.6%)            17.64h  = 46.3%

    Bash calls >= 60s, under an hour: 310 calls, 9.90h
    of those, ALREADY BACKGROUNDED: 0

Zero. Not a low number -- none. The Bash tool has taken `run_in_background` the whole time and
nothing has ever used it for a long command, so 9.9 hours of this project's wall clock is a
session sitting and watching a command it could have walked away from.

WHY THIS IS NOT A PATTERN LIST. The obvious build is a list of slow-looking commands. It is the
wrong build, and the measurement says so: the 310 long calls spread across kubectl (19.9%), CI
and gate runs (20.4%), polling loops (16.5%), grep sweeps (8.3%), git transfers (6.4%), scanners
(4.9%) and a 19.1% tail of things no list would have held. A list would refuse novel correct work
and miss most of the cost. So this measures instead: a signature is slow because it HAS BEEN slow
here, on this machine, at least three times. A command nobody has timed can never trip it.

WHY IT WARNS AND DOES NOT REFUSE (LAW 38). The estate has commands that are long by design --
`tofu plan`, `bin/idp-oke-rebuild --check`, `bin/idp-vault-reads` over a 90-minute audit window --
and a fence that refused them would be an outage. The note costs a session nothing and names the
flag; a refusal would cost it a turn to learn what it already knew.

  slow_commands.mark_start(session, cmd)   PreToolUse, from inside rule-guard.py (no new process)
  slow_commands.note(cmd, backgrounded)    PreToolUse, the warning or None
  slow-commands.py --post                  PostToolUse, closes the timing and records it
  slow-commands.py --report                what is slow here, newest measurement first
  slow-commands.py --selftest              prove it
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("CLAUDE_STATE") or (Path.home() / ".claude" / "state"))
TIMINGS = STATE / "command-timings.jsonl"
INFLIGHT = STATE / "inflight"

MIN_RUNS = 3  # never speak about a signature measured fewer times than this
SLOW_S = 90  # the median a signature must reach before it is worth a note
KEEP = 20  # measurements kept per signature; a command that got faster stops warning
MAX_BYTES = 4_000_000

#: Wrappers that say nothing about what is being run. `bin/idp-kube get pods` and
#: `bin/idp-kube get nodes` are one signature; `time pytest` and `pytest` are one signature.
# `timeout\s+\S+` used to sit in this list, and never fired: the pattern is matched against a
# single word, so the space could not be there. `timeout` is skipped as the wrapper it is and
# its seconds argument is dropped by the digit rule in _is_command.
_NOISE = re.compile(r"^(sudo|time|nice|env|exec|command|nohup|timeout|gtimeout|xargs)$")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


#: A shell loop that re-checks something until it changes. These are the worst single offenders --
#: measured here, 33 of them at 60s or more, 1.63h, several sitting on the 600s tool cap -- and
#: backgrounding one only moves a 600s block to a 600s background poll. The Monitor tool is the
#: primitive that already exists for waiting on a condition, so a loop gets told that instead.
_LOOP = re.compile(
    r"(^|[\s;&|(])(while|until)\s|(^|[\s;&|(])for\s+\w+\s+in\s+\$\(seq\b"
)

#: What a command name can look like. Everything else is a fragment my walker latched onto -- a
#: quote, a shell function body, a path from someone's iCloud, a bare flag -- and a warning that
#: names one of those is noise, which is the thing the founder said not to build.
_COMMAND = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._+-]{0,40}$")

#: Shell keywords and builtins: real words, but never the thing that was slow.
_KEYWORD = frozenset(
    (
        "while",
        "until",
        "for",
        "do",
        "done",
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "case",
        "esac",
        "function",
        "select",
        "in",
        "return",
        "local",
        "declare",
        "typeset",
        "setopt",
        "shopt",
        "eval",
        "trap",
        "wait",
        "read",
        "echo",
        "printf",
        "true",
        "false",
        "test",
    )
)


def _is_command(binary: str) -> bool:
    """A capital letter is the tell for prose: `Support` and `Missing` came out of the seeding run
    as signatures, from commands whose first segment was a word in a message rather than a
    program. No command on this machine starts with one."""
    return (
        bool(_COMMAND.match(binary))
        and binary not in _KEYWORD
        and not binary[0].isupper()
    )


def _quiet_failure(exc: BaseException) -> None:
    """A timing is not worth a broken turn, but a recorder that dies silently is the trap this
    estate keeps falling into (session-recorder.py wrote nothing for 17 days and reported success).
    So: swallow the turn-breaking part, and leave one line an hour where a reader will find it."""
    try:
        f = STATE / "slow-commands-errors.log"
        if f.exists() and time.time() - f.stat().st_mtime < 3600:
            return
        STATE.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(
                f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
                f"{type(exc).__name__}: {exc}\n"
            )
    except OSError:
        return


def signature(cmd: str) -> str:
    """The binary and its first subcommand, with every path, flag and value dropped.

    Two calls share a signature when they will cost about the same. `bin/idp-ci` in one checkout
    and `bin/idp-ci` in another are the same cost; `gh run view 123` and `gh run view 456` are the
    same cost; `grep -rn "a" .` and `grep -rn "b" .` are the same cost.
    """
    text = cmd.strip()
    if _LOOP.search(text):
        return "shell loop"
    # Walk the segments, not just the first: `set -o pipefail; cd /a && bin/idp-ci` is idp-ci.
    for seg in re.split(r"(?:\|\||&&|\||;|\n)", text):
        words = seg.split()
        while words and (
            _ASSIGN.match(words[0]) or _NOISE.match(words[0]) or words[0].isdigit()
        ):
            words = words[1:]
        if not words or words[0] in ("set", "cd", "export", "unset", "source"):
            continue  # shell setup says nothing about what will be slow
        binary = os.path.basename(words[0])
        if not _is_command(binary):
            continue  # a fragment, not a command; try the next segment
        if binary in ("python3", "python", "node", "sh", "bash", "zsh"):
            if len(words) > 1 and (
                words[1] in ("-", "-c", "-m") or words[1].startswith("<<")
            ):
                return f"{binary} -"  # a heredoc script: one signature for all of them
            return (
                f"{binary} {os.path.basename(words[1])}" if len(words) > 1 else binary
            )
        # Keep up to two bare subcommand words (`gh run view`, `git remote add`); a path, a URL,
        # a number or a flag value is an argument and is dropped.
        sub = []
        for w in words[1:]:
            if w.startswith("-") or not re.fullmatch(r"[a-z][a-z0-9:_-]{0,20}", w):
                break
            sub.append(w)
            if len(sub) == 2:
                break
        return " ".join([binary, *sub]).strip()
    return ""


def mark_start(session: str, cmd: str) -> None:
    """PreToolUse. Never raises: a timing is not worth a broken turn."""
    try:
        sig = signature(cmd)
        if not sig or not session:
            return
        INFLIGHT.mkdir(parents=True, exist_ok=True)
        (INFLIGHT / f"{session[:8]}.json").write_text(
            json.dumps({"sig": sig, "t": time.time()})
        )
    except (OSError, ValueError) as exc:
        _quiet_failure(exc)


def close(session: str) -> tuple[str, float] | None:
    """PostToolUse. Returns the signature and how long it actually took."""
    f = INFLIGHT / f"{session[:8]}.json"
    try:
        d = json.loads(f.read_text())
        f.unlink()
    except (OSError, ValueError, KeyError):
        return None
    secs = time.time() - float(d["t"])
    return (str(d["sig"]), secs) if 0 <= secs < 86400 else None


def record(sig: str, secs: float) -> None:
    try:
        if secs < 10:
            return  # only slow things are worth the disk
        STATE.mkdir(parents=True, exist_ok=True)
        if TIMINGS.exists() and TIMINGS.stat().st_size > MAX_BYTES:
            TIMINGS.replace(TIMINGS.with_suffix(".jsonl.1"))
        with open(TIMINGS, "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "sig": sig,
                        "s": round(secs, 1),
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                )
                + "\n"
            )
    except (OSError, ValueError) as exc:
        _quiet_failure(exc)


def history(path: Path | None = None) -> dict[str, list[float]]:
    """Every recorded measurement, newest KEEP per signature. Resolved per call, never at import:
    a long-lived reader must see what was written after it started."""
    p = path or TIMINGS
    out: dict[str, list[float]] = {}
    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return out
    for ln in lines:
        if not ln.startswith("{"):
            continue  # a half-written line from a killed process
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and "sig" in r and "s" in r:
            out.setdefault(str(r["sig"]), []).append(float(r["s"]))
    return {k: v[-KEEP:] for k, v in out.items()}


def note(cmd: str, backgrounded: bool, path: Path | None = None) -> str | None:
    """The warning, or None. Silent on anything backgrounded, novel, or not actually slow."""
    if backgrounded:
        return None
    sig = signature(cmd)
    if not sig:
        return None
    runs = history(path).get(sig, [])
    if len(runs) < MIN_RUNS:
        return None
    med = statistics.median(runs)
    if med < SLOW_S:
        return None
    if sig == "shell loop":
        return (
            f"This is a wait loop, and wait loops here have a median of {med:.0f}s and a longest "
            f"of {max(runs):.0f}s -- several sit on the 600s tool cap. Backgrounding one only "
            f"moves a 600s foreground block to a 600s background poll. Use the Monitor tool, "
            f"which is the primitive for waiting on a condition and returns as soon as it is "
            f"true. Measured across this project: 33 wait loops of 60s or more, 1.63 hours."
        )
    return (
        f"`{sig}` has been measured {len(runs)} times on this machine: median {med:.0f}s, "
        f"longest {max(runs):.0f}s. This call is in the foreground, so the session stops until "
        f"it returns. Pass run_in_background: true to the Bash tool and keep working; you are "
        f"re-invoked when it exits. Measured across this project: 310 Bash calls ran 60s or "
        f"longer, none of them backgrounded, 9.9 hours of sitting still."
    )


def cmd_post() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
            return 0
        done = close(str(payload.get("session_id") or ""))
        if done:
            record(*done)
    except (OSError, ValueError, TypeError) as exc:
        _quiet_failure(exc)
    return 0


def cmd_report() -> int:
    h = history()
    if not h:
        print("nothing measured yet")
        return 0
    rows = sorted(
        ((statistics.median(v), len(v), max(v), k) for k, v in h.items()), reverse=True
    )
    print(f"{'median':>8} {'max':>8} {'runs':>5}  signature")
    for med, n, mx, sig in rows[:40]:
        flag = "  <- warns" if n >= MIN_RUNS and med >= SLOW_S else ""
        print(f"{med:8.0f} {mx:8.0f} {n:5}  {sig}{flag}")
    return 0


def selftest() -> int:
    import tempfile

    fails = []

    def check(name, ok, detail=""):
        print(
            f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + str(detail) if detail else ''}"
        )
        if not ok:
            fails.append(name)

    check(
        "a wrapper and its command are one signature",
        signature("time pytest -q") == signature("pytest -q") == "pytest",
        signature("time pytest -q"),
    )
    check(
        "set -o pipefail is not the command",
        signature("set -o pipefail; bin/idp-ci") == "idp-ci",
        signature("set -o pipefail; bin/idp-ci"),
    )
    check(
        "cd somewhere && x is x",
        signature("cd /a/b && bin/idp-ci --fast") == "idp-ci",
        signature("cd /a/b && bin/idp-ci --fast"),
    )
    check(
        "the subcommand is kept, the arguments are not",
        signature("gh run view 12345 --log")
        == signature("gh run view 99 --log")
        == "gh run view",
        signature("gh run view 12345 --log"),
    )
    check(
        "two checkouts of one tool are one signature",
        signature("/x/bin/idp-kube get pods") == signature("/y/bin/idp-kube get pods"),
        signature("/x/bin/idp-kube get pods"),
    )
    check(
        "a wait loop is its own signature",
        signature("for i in $(seq 1 20); do gh run view; sleep 20; done")
        == "shell loop",
    )
    check(
        "a while loop is too",
        signature("while ! curl -sf localhost:80; do sleep 5; done") == "shell loop",
    )
    check(
        "the seconds argument of timeout is not the command",
        signature("timeout 90 du -sh /Users/x/Library") == "du",
    )
    check(
        "nor after gtimeout, whose seconds used to be read as the program",
        signature("gtimeout 60 grep -rn x .") == "grep",
    )
    check(
        "a shell function body is not a command",
        signature('k(){ kubectl "$@"; }; k get pods') not in ("k(){", "k(){ kubectl"),
        signature('k(){ kubectl "$@"; }; k get pods'),
    )
    check(
        "a bare flag is not a command",
        signature("-oE '[a-z]+' file") == "",
        signature("-oE '[a-z]+' file"),
    )
    check(
        "a quoted fragment is not a command",
        signature('"$V" --check') == "",
        signature('"$V" --check'),
    )
    check(
        "a shell keyword is not a command",
        signature("setopt nullglob; ls") == "ls",
        signature("setopt nullglob; ls"),
    )
    check(
        "a heredoc script is one signature",
        signature("python3 - <<'PY'\nprint(1)\nPY") == "python3 -",
    )
    check(
        "a bash heredoc is the same signature shape",
        signature("bash <<'SH'\necho hi\nSH") == "bash -",
        signature("bash <<'SH'\necho hi\nSH"),
    )
    check(
        "a capitalised word is prose, not a command",
        signature("Support ended here") == "",
        signature("Support ended here"),
    )
    check("bare time is not a command", signature("time") == "", signature("time"))

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        p.write_text(
            "".join(
                json.dumps({"sig": "trivy config", "s": 149.0}) + "\n" for _ in range(4)
            )
        )
        loops = Path(td) / "loops.jsonl"
        loops.write_text(
            "".join(
                json.dumps({"sig": "shell loop", "s": 300.0}) + "\n" for _ in range(5)
            )
        )
        ln = note("until gh run view; do sleep 10; done", False, loops)
        check(
            "a slow wait loop is pointed at Monitor, not at backgrounding",
            bool(ln) and "Monitor" in ln and "run_in_background" not in ln,
        )

        n = note("trivy config platform/", False, p)
        check("a signature measured slow 4 times warns", bool(n) and "149s" in n)
        check(
            "the note names the flag that fixes it",
            bool(n) and "run_in_background" in n,
        )
        check(
            "the same call backgrounded is silent",
            note("trivy config x", True, p) is None,
        )

        p.write_text(
            "".join(
                json.dumps({"sig": "trivy config", "s": 149.0}) + "\n" for _ in range(2)
            )
        )
        check(
            f"measured fewer than {MIN_RUNS} times says nothing",
            note("trivy config x", False, p) is None,
        )

        p.write_text(
            "".join(
                json.dumps({"sig": "ruff check", "s": 12.0}) + "\n" for _ in range(9)
            )
        )
        check(
            "a fast command measured many times says nothing",
            note("ruff check .", False, p) is None,
        )

        check(
            "a command never measured says nothing",
            note("some-new-tool run", False, p) is None,
        )

        # A command that GOT faster must stop warning: only the newest KEEP count.
        rows = [json.dumps({"sig": "bin/idp-ci", "s": 400.0}) for _ in range(KEEP)]
        rows += [json.dumps({"sig": "bin/idp-ci", "s": 5.0}) for _ in range(KEEP)]
        p.write_text("\n".join(rows) + "\n")
        check(
            "a command that got faster stops warning",
            note("bin/idp-ci", False, p) is None,
        )

        # The round trip, through the real files.
        global STATE, TIMINGS, INFLIGHT
        STATE, TIMINGS, INFLIGHT = Path(td), Path(td) / "c.jsonl", Path(td) / "inflight"
        mark_start("sess1234abcd", "cd /a && bin/idp-ci --fast")
        d = close("sess1234abcd")
        check(
            "start and close pair up into a duration",
            d is not None and d[0] == "idp-ci" and d[1] >= 0,
            d,
        )
        check("closing twice returns nothing", close("sess1234abcd") is None)
        record("bin/idp-ci", 300.0)
        record("bin/idp-ci", 4.0)
        check(
            "a fast measurement is not stored",
            history(TIMINGS).get("bin/idp-ci") == [300.0],
            history(TIMINGS),
        )
        check(
            "closing a session that never started returns nothing",
            close("nope0000") is None,
        )

    old = sys.stdin
    sys.stdin = open(os.devnull)
    try:
        check("--post returns 0 on garbage stdin", cmd_post() == 0)
    finally:
        sys.stdin = old

    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        sys.exit(selftest())
    if "--post" in a:
        sys.exit(cmd_post())
    if "--report" in a:
        sys.exit(cmd_report())
    print(__doc__)
    sys.exit(0)
