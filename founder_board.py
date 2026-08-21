#!/usr/bin/env python3
"""The founder's board: what is done, what is broken, what is waiting on him.

Founder directive 2026-08-21: "we dothave a borard", "should notave to be asking these
questions", "need to know what is done, what is outstanding before going tinto liower level
detail", "so updates neeed to be top notch".

WHAT THIS IS FOR. He was opening the same page an hour apart and seeing nothing change, and
having to ask each time. A board he can open answers the question without a person in the loop,
which is the "frictioless and barelt any hunan inloop" requirement applied to reporting itself.

WHY IT IS GENERATED AND NEVER WRITTEN BY HAND. This estate's most expensive repeated failure is
prose that was true once. A hand-written status page drifts from the machine within hours and
then costs more than no page, because it is believed. Every row here comes from a command, and
every row carries the command that produced it so any line can be re-run and checked.

THREE RULES THE COLLECTORS OBEY, each one a failure this estate has already paid for:

  1. A collector that fails reports UNKNOWN with the reason. It NEVER reports zero.
     A dead probe and a clean probe both print no findings; only one of them is good news.
     (memory: an-audit-that-crashes-reports-nothing)
  2. A non-zero exit is not automatically an error. process_audit.py exits 1 BECAUSE it found
     failures -- that is it working. Each collector says for itself which exits are fine.
  3. Every row carries the age of its measurement. A number with no age is a claim about the
     past presented as a claim about now.

    python3 ~/.claude/scripts/founder_board.py              # print it
    python3 ~/.claude/scripts/founder_board.py --html OUT   # write the page
    python3 ~/.claude/scripts/founder_board.py --json       # machine-readable
    python3 ~/.claude/scripts/founder_board.py --selftest
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import os
import shutil
import subprocess
import sys
import ast
import datetime as dt
import time

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".claude", "state", "founder_board.json")
PROSPECTOR = os.path.join(HOME, "Documents", "code", "prospector")
GH_REPO = "chidionyema/prospector"
LIVE_URL = "https://mumchimp.com"
SCRIPTS = os.path.join(HOME, ".claude", "scripts")

GOOD, BAD, WARN, UNKNOWN = "good", "bad", "warn", "unknown"


#: Where tools live on this machine, ahead of whatever PATH the caller happened to have.
#: launchd hands a job PATH=/usr/bin:/bin:/usr/sbin:/sbin and nothing else, and `gh` lives in
#: /usr/local/bin. So under `com.founder.board` -- the hourly job that writes the page the
#: founder actually reads -- every row that shells out to gh reported
#: "FileNotFoundError: [Errno 2] No such file or directory: 'gh'", including the open pull
#: requests row, while gh worked perfectly in any terminal. Measured 2026-08-21: 8 of the
#: page's rows read UNKNOWN for this one reason.
#:
#: The fix is here rather than in the plist because a PATH in the plist is right only for the
#: one caller that has it. A second copy of this page, run by hand or by a different job, is
#: then correct by accident.
_TOOL_DIRS = (os.path.join(HOME, ".local", "bin"), "/usr/local/bin", "/opt/homebrew/bin")


def tool_path() -> str:
    """PATH for a subprocess: the known tool directories, then the caller's own."""
    return os.pathsep.join((*_TOOL_DIRS, os.environ.get("PATH", "")))


def sh(cmd: list[str], timeout: int, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a command. Returns (rc, stdout, stderr). rc 124 is this function's timeout."""
    try:
        # execvpe looks argv[0] up in the PATH it is HANDED, not the parent's. Measured
        # 2026-08-21: with PATH stripped to launchd's own, `gh --version` returns 0 through
        # env= and raises FileNotFoundError without it. So env= is the whole fix; resolving
        # argv[0] here as well would be dead code that no mutation can catch.
        env = {**os.environ, "PATH": tool_path()}
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                           env=env)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except (OSError, ValueError) as e:
        return 127, "", f"{type(e).__name__}: {e}"


class Row:
    __slots__ = ("state", "label", "value", "detail", "command", "measured_at")

    def __init__(self, state, label, value, detail="", command=""):
        self.state, self.label, self.value = state, label, value
        self.detail, self.command = detail, command
        self.measured_at = time.time()

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


def _unknown(label, why, command=""):
    """The only honest answer when a probe could not run. Never a zero."""
    return Row(UNKNOWN, label, "UNKNOWN", why, command)


# --------------------------------------------------------------------------- collectors

def collect_spend() -> list[Row]:
    """Money. This is the platform view and it goes first for that reason.

    It reports WHERE the money goes, not only how much, because the two rows this used to
    print sent the founder at the wrong lever. Measured 2026-08-21: the board said "spend
    halt DISARMED -- nothing stops the spend" against a $516.79 day. `halt_usd` fires on the
    DAEMON leg only (estate-budget.json says so in its own note), and the daemon spent $1.51
    of that. Arming it would have saved 0.3% and stopped the engine. 99.7% was five
    concurrent interactive coding sessions, which no halt in this estate can touch.
    """
    cmd = ["/usr/local/bin/python3",
           os.path.join(HOME, ".claude", "scripts", "estate_spend.py"), "--json"]
    rc, out, err = sh(cmd, 240)
    if rc not in (0, 2) or not out.strip():      # rc 2 is --cap's "over the line", unused here
        return [_unknown("Claude spend today", err.strip()[:200] or f"exit {rc}",
                         " ".join(cmd))]
    try:
        spend = json.loads(out)
    except json.JSONDecodeError as e:
        return [_unknown("Claude spend today", f"meter printed no JSON: {e}", " ".join(cmd))]

    budget_path = os.path.join(HOME, ".claude", "estate-budget.json")
    try:
        with open(budget_path) as fh:
            budget = json.load(fh)
        cap = float(budget.get("warn_usd") or 0)
        halt = float(budget.get("halt_usd") or 0)
        budget_err = ""
    except (OSError, ValueError, json.JSONDecodeError) as e:
        cap = halt = 0.0
        budget_err = f"{type(e).__name__}: {e}"

    total = float(spend.get("total") or 0)
    by_owner = spend.get("by_owner") or {}
    # The daemon leg is the ONLY thing halt_usd can stop, so it is the only number that makes
    # arming it a decision rather than a gesture.
    daemon = sum(v for k, v in by_owner.items() if "daemon" in k)

    rows: list[Row] = []
    if cap:
        rows.append(Row(BAD if total > cap else GOOD, "Claude spend today",
                        f"${total:,.2f} of a ${cap:,.0f} cap",
                        f"{total / cap:.1f}x the cap" if total > cap else "inside the cap",
                        " ".join(cmd)))
    else:
        rows.append(Row(WARN, "Claude spend today", f"${total:,.2f}",
                        budget_err or "no warn_usd set, so there is no line to be over",
                        " ".join(cmd)))

    if by_owner:
        top, top_usd = max(by_owner.items(), key=lambda kv: kv[1])
        share = f"{top_usd / total * 100:.0f}%" if total else "n/a"
        rows.append(Row(BAD if cap and total > cap else GOOD, "Where the money goes",
                        f"{top} — ${top_usd:,.2f}",
                        f"{share} of today's spend, over {spend.get('requests', 0):,} requests "
                        f"in {spend.get('files', 0)} transcripts",
                        " ".join(cmd)))
    else:
        rows.append(_unknown("Where the money goes", "the meter reported no owners",
                             " ".join(cmd)))

    # NOT "nothing stops the spend". Say what arming it would actually have stopped today.
    armed = halt > 0
    rows.append(Row(GOOD if armed else WARN, "Automatic spend halt",
                    f"ARMED at ${halt:,.0f}" if armed else "DISARMED",
                    (f"stops the daemon leg only; that leg is ${daemon:,.2f} of today's "
                     f"${total:,.2f}, so arming it cannot touch the rest")
                    if not armed else
                    f"fires on the daemon leg, ${daemon:,.2f} so far today",
                    f"grep halt_usd {budget_path}"))
    return rows


def collect_estate_checks() -> list[Row]:
    """The estate's own auditor. Its exit 1 means it found problems -- that is it working."""
    cmd = [os.path.join(PROSPECTOR, ".venv", "bin", "python"),
           os.path.join(PROSPECTOR, "scripts", "process_audit.py"), "--json"]
    rc, out, err = sh(cmd, 600, cwd=PROSPECTOR)
    if rc not in (0, 1):
        return [_unknown("Estate checks", err.strip()[:200] or f"exit {rc}", " ".join(cmd))]
    try:
        payload = json.loads(out)
    except ValueError as e:
        return [_unknown("Estate checks", f"audit printed no JSON ({e})", " ".join(cmd))]
    failing = [(s["title"], r) for s in payload.get("sections", [])
               for r in s.get("rows", []) if r.get("grade") == "bad"]
    rows = [Row(GOOD if not failing else BAD, "Estate checks failing",
                str(len(failing)),
                f"{payload.get('warnings', 0)} warnings as well", " ".join(cmd))]
    for title, r in failing:
        rows.append(Row(BAD, f"{title} — {r['name']}", "FAIL", r.get("detail", "")[:220],
                        " ".join(cmd)))
    return rows


def classify_checks(checks: list) -> tuple[list[str], int]:
    """Split a PR's checks into (names that really failed, how many are still running).

    A check still running reports conclusion "" on a CheckRun and null on a StatusContext,
    NEITHER of which is a failure. Measured 2026-08-21 on PR #557: `changes` was QUEUED and
    `keep` was IN_PROGRESS, both with conclusion "", and the first draft of this board printed
    "red: changes, keep". A board that cries wolf about the founder's own pipeline is worse than
    no board -- it is the same defect this session had just fixed in the estate auditor.
    """
    done = [c for c in checks if (c.get("conclusion") or "")]
    red = sorted({c.get("name") or c.get("context") or "?" for c in done
                  if c["conclusion"] not in ("SUCCESS", "NEUTRAL", "SKIPPED")})
    return red, len(checks) - len(done)


def collect_prs() -> list[Row]:
    """What is in flight. A PR nobody can merge is the pipeline stopped (LAW 12)."""
    cmd = ["gh", "pr", "list", "--repo", "chidionyema/prospector", "--limit", "30",
           "--json", "number,title,mergeable,statusCheckRollup,createdAt,isDraft"]
    rc, out, err = sh(cmd, 90)
    if rc != 0:
        return [_unknown("Open pull requests", err.strip()[:200] or f"exit {rc}", " ".join(cmd))]
    try:
        prs = json.loads(out)
    except ValueError as e:
        return [_unknown("Open pull requests", str(e), " ".join(cmd))]
    rows = [Row(GOOD if len(prs) <= 5 else WARN, "Open pull requests", str(len(prs)),
                "", " ".join(cmd))]
    now = time.time()
    for pr in prs:
        checks = pr.get("statusCheckRollup") or []
        red, pending = classify_checks(checks)
        try:
            age_h = (now - time.mktime(time.strptime(pr["createdAt"], "%Y-%m-%dT%H:%M:%SZ"))
                     + time.timezone) / 3600
        except (KeyError, ValueError):
            age_h = float("nan")
        conflicting = pr.get("mergeable") == "CONFLICTING"
        state = BAD if (red or conflicting) else (WARN if pending else GOOD)
        what = ("needs a rebase" if conflicting else
                f"red: {', '.join(red)}" if red else
                f"{pending} check(s) still running" if pending else "green, mergeable")
        rows.append(Row(state, f"PR #{pr['number']} — {pr['title'][:58]}", what,
                        f"open {age_h:.0f}h", f"gh pr view {pr['number']}"))
    return rows


def collect_requirements() -> list[Row]:
    """What the founder asked for, and how much of it is proven done."""
    cmd = ["git", "-C", PROSPECTOR, "show", "origin/main:docs/REQUIREMENTS.md"]
    rc, out, err = sh(cmd, 60)
    if rc != 0:
        return [_unknown("Requirements register", err.strip()[:160] or f"exit {rc}",
                         " ".join(cmd))]
    tally, total = {}, 0
    for line in out.splitlines():
        if not line.startswith("| R"):
            continue
        total += 1
        cells = [c.strip() for c in line.split("|")]
        state = "UNSTATED"
        for c in cells:
            bare = c.replace("*", "").strip()
            if bare in ("DONE", "PARTLY", "NOT STARTED", "IN PROGRESS", "unproven"):
                state = bare
                break
            if bare.startswith("DONE"):          # "DONE (engine + config page)"
                state = "DONE"
                break
        tally[state] = tally.get(state, 0) + 1
    if not total:
        return [_unknown("Requirements register", "no R-rows found on origin/main",
                         " ".join(cmd))]
    done = tally.get("DONE", 0)
    rows = [Row(GOOD if done == total else WARN, "Requirements proven done",
                f"{done} of {total}",
                ", ".join(f"{v} {k.lower()}" for k, v in sorted(tally.items())),
                " ".join(cmd))]
    return rows


def collect_launchd() -> list[Row]:
    """Every job that is supposed to keep this estate running by itself."""
    rc, out, err = sh(["launchctl", "list"], 30)
    if rc != 0:
        return [_unknown("Background jobs", err.strip()[:160] or f"exit {rc}", "launchctl list")]
    watched, dead = 0, []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid, status, label = parts
        if not (label.startswith("com.prospector") or label.startswith("com.estate")
                or label.startswith("ai.hermes") or label.startswith("com.chidionyema")):
            continue
        watched += 1
        try:
            code = int(status)
        except ValueError:
            continue
        # A negative status is a signal, which for a periodic job usually means it is running
        # right now. Only a positive exit code is a job that ran and failed.
        if code > 0:
            dead.append(f"{label} (exit {code})")
    rows = [Row(GOOD if not dead else BAD, "Background jobs failing",
                f"{len(dead)} of {watched}", "; ".join(dead[:6]), "launchctl list")]
    return rows


def collect_founder_decisions() -> list[Row]:
    """Questions only he can answer. They are not blocked on work, they block work."""
    cmd = ["git", "-C", PROSPECTOR, "show", "origin/main:docs/REQUIREMENTS.md"]
    rc, out, _ = sh(cmd, 60)
    if rc != 0:
        return [_unknown("Waiting on the founder", f"exit {rc}", " ".join(cmd))]
    # `| Q | Question | ...` is the TABLE HEADER, not a question. Counting it made the board say
    # 5 rulings outstanding when there were 4, and printed the word "Question" as the first one.
    qs = [l for l in out.splitlines()
          if l.startswith("| Q") and "---" not in l and l.split("|")[1].strip() != "Q"]
    return [Row(WARN if qs else GOOD, "Waiting on a founder ruling", str(len(qs)),
                "; ".join(l.split("|")[2].strip()[:70] for l in qs[:4]), " ".join(cmd))]



def _gh_runs(workflow: str, limit: int = 8) -> list[dict] | None:
    """The last runs of one workflow, or None when the question could not be asked."""
    cmd = ["gh", "run", "list", "--repo", GH_REPO, "--limit", str(limit),
           "--json", "databaseId,status,conclusion,createdAt"]
    if workflow:
        cmd[4:4] = ["--workflow", workflow]
    rc, out, _ = sh(cmd, 45)
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return None


def _age(iso: str) -> str:
    """`2026-08-21T09:58:22Z` -> `21m ago`. Every row carries the age of its measurement."""
    try:
        t = time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (ValueError, TypeError):
        return "age unknown"
    m = int((time.time() - t) / 60)
    return f"{m}m ago" if m < 90 else f"{m // 60}h ago"


def _run_row(label: str, runs: list[dict] | None, workflow: str) -> Row:
    cmd = f"gh run list --repo {GH_REPO} --workflow {workflow} --limit 1"
    if runs is None:
        return _unknown(label, "gh run list failed or returned no json", cmd)
    if not runs:
        return _unknown(label, "this workflow has never run", cmd)
    r = runs[0]
    if r.get("status") != "completed":
        return Row(WARN, label, f"{r.get('status')} now",
                   f"run {r.get('databaseId')}, started {_age(r.get('createdAt', ''))}", cmd)
    ok = r.get("conclusion") == "success"
    return Row(GOOD if ok else BAD, label, str(r.get("conclusion")),
               f"run {r.get('databaseId')}, {_age(r.get('createdAt', ''))}", cmd)


def collect_shipped_to_live() -> list[Row]:
    """MERGED IS NOT OPERATIONAL, and nothing in this estate watched the difference.

    The founder, 2026-08-21: "when you ship, is it operational?" and "we cant have things working
    in the ark black bes". The chain a merge has to survive is merge -> deploy -> the bytes on the
    live site -> the post-deploy smoke that grades them. Every link of it ran in the dark: a
    session could truthfully say "merged" while the deploy failed, or the deploy could go green
    while the site served the wrong thing. These rows are that chain, one row per link.
    """
    rows = [_run_row("Store deploy, last run", _gh_runs("deploy-store-web.yml"),
                     "deploy-store-web.yml"),
            _run_row("Engine deploy, last run", _gh_runs("deploy-engine.yml"),
                     "deploy-engine.yml")]

    smokes = _gh_runs("e2e-live-smoke.yml")
    rows.append(_run_row("Live smoke, last run", smokes, "e2e-live-smoke.yml"))

    # THE DARK NUMBER. Work that reached main and has never been graded against the live site.
    green = next((r for r in (smokes or [])
                  if r.get("status") == "completed" and r.get("conclusion") == "success"), None)
    if green is None:
        rows.append(Row(BAD, "Merges never graded against live", "ALL of them",
                        "no live smoke has EVER concluded green, so nothing merged is verified",
                        f"gh run list --repo {GH_REPO} --workflow e2e-live-smoke.yml"))
    else:
        since = green["createdAt"]
        cmd = ["gh", "pr", "list", "--repo", GH_REPO, "--state", "merged", "--limit", "40",
               "--json", "number,mergedAt,title"]
        rc, out, _ = sh(cmd, 45)
        try:
            merged = [p for p in json.loads(out) if (p.get("mergedAt") or "") > since] if rc == 0 else None
        except (json.JSONDecodeError, TypeError):
            merged = None
        if merged is None:
            rows.append(_unknown("Merges never graded against live", "gh pr list failed",
                                 " ".join(cmd)))
        else:
            rows.append(Row(GOOD if not merged else WARN, "Merges never graded against live",
                            str(len(merged)),
                            "; ".join(f"#{p['number']} {p['title'][:40]}" for p in merged[:4])
                            or f"last green smoke {_age(since)}", " ".join(cmd)))

    # The site itself. A deploy that says success and a page that does not answer are both
    # possible at the same time, so this asks the site rather than the pipeline.
    import urllib.error
    import urllib.request
    started = time.time()
    try:
        with urllib.request.urlopen(LIVE_URL, timeout=25) as resp:
            body = resp.read()
            ms = int((time.time() - started) * 1000)
            good = resp.status == 200 and len(body) > 2000
            rows.append(Row(GOOD if good else BAD, "mumchimp.com answering",
                            f"HTTP {resp.status}", f"{len(body)} bytes in {ms}ms",
                            f"curl -si {LIVE_URL} | head -1"))
    except (urllib.error.URLError, OSError, ValueError) as ex:
        rows.append(Row(BAD, "mumchimp.com answering", "NO ANSWER",
                        f"{type(ex).__name__}: {ex}", f"curl -si {LIVE_URL} | head -1"))
    return rows


def _selftest_scripts() -> tuple[list[str], list[str]]:
    """(scripts that DEFINE a selftest, scripts that only mention one).

    The first version grepped for the literal `--selftest` anywhere in the file, and that is
    grading a proxy -- the estate's named failure class, in the board that reports it. Measured
    2026-08-21: `reflect.py` was reported as "a guard claiming a selftest it does not have"
    because the string sits inside a DATA table at reflect.py:588, where it is the remediation
    command for a different guard. The file never advertised anything.

    A definition is the honest test, so this reads the AST. The second list exists because an
    allow-list with a silent miss case is how 10 criticals were dropped in 18 hours: a script
    that runs a selftest without defining a function named for one is REPORTED, never dropped.
    """
    defined: list[str] = []
    mentioned: list[str] = []
    try:
        names = sorted(os.listdir(SCRIPTS))
    except OSError:
        return defined, mentioned
    for name in names:
        if not name.endswith(".py"):
            continue
        path = os.path.join(SCRIPTS, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            tree = ast.parse(text)
        except (OSError, SyntaxError, ValueError):
            continue
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name.lstrip("_") == "selftest" for n in ast.walk(tree)):
            defined.append(path)
        elif "--selftest" in text and _advertises_selftest(tree):
            mentioned.append(path)
    return defined, mentioned


def _advertises_selftest(tree: "ast.AST") -> bool:
    """True when the file OFFERS `--selftest` to a caller, rather than merely containing it.

    The three ways a script can offer one without defining a function named for it: say so in
    its module docstring, register it with argparse, or test `sys.argv` directly. Anything else
    holding the literal is data -- `reflect.py:588` carries it as the remediation command for a
    DIFFERENT guard, and the board accused it of false advertising for three builds.
    """
    doc = ast.get_docstring(tree) or ""
    if "--selftest" in doc:
        return True
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_argument"):
            for a in n.args:
                if isinstance(a, ast.Constant) and a.value == "--selftest":
                    return True
        if isinstance(n, ast.Compare) and any(isinstance(o, ast.In) for o in n.ops):
            if (isinstance(n.left, ast.Constant) and n.left.value == "--selftest"
                    and "argv" in ast.dump(n)):
                return True
    return False


def collect_hooks_and_guards() -> list[Row]:
    """The guards are the estate's immune system, and NOTHING was watching them.

    Founder, 2026-08-21: "eveeven the hoks annd guards and everyhting else". Two ways a guard
    dies silently. Its script can be deleted or renamed while settings.json still names it -- the
    hook then fails open on every turn and no one is told. Or its own selftest can start failing:
    measured on the first run of this collector, `pr-freeze.py --selftest` reported 3 failed, so
    the freeze was not blocking `gh pr create` at all while every session believed it was.
    """
    rows: list[Row] = []
    settings = os.path.join(HOME, ".claude", "settings.json")
    try:
        with open(settings, encoding="utf-8") as fh:
            hooks = json.load(fh).get("hooks", {})
    except (OSError, json.JSONDecodeError) as ex:
        rows.append(_unknown("Hooks registered", f"{type(ex).__name__}: {ex}", f"cat {settings}"))
        hooks = None
    if hooks is not None:
        total, missing = 0, []
        for event, groups in hooks.items():
            for group in groups if isinstance(groups, list) else []:
                for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                    cmd = str(hook.get("command", ""))
                    total += 1
                    # Any ~/.claude/scripts path the command names must exist, or the hook is a
                    # no-op that fails open and says nothing.
                    for tok in cmd.replace('"', " ").replace("'", " ").split():
                        tok = os.path.expanduser(tok.strip())
                        if tok.startswith(SCRIPTS) and not os.path.exists(tok):
                            missing.append(f"{event}: {os.path.basename(tok)}")
        rows.append(Row(GOOD if not missing else BAD, "Hooks whose script is missing",
                        f"{len(missing)} of {total}", "; ".join(missing[:6]),
                        "python3 -c \"import json;print(json.load(open('~/.claude/settings.json'))['hooks'])\""))

    scripts, mentioned_only = _selftest_scripts()
    if not scripts:
        rows.append(_unknown("Guard selftests", f"no scripts found under {SCRIPTS}",
                             f"ls {SCRIPTS}/*.py"))
        return rows

    from concurrent.futures import ThreadPoolExecutor
    def one(path):
        return path, sh([sys.executable, path, "--selftest"], 30)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, scripts))

    failed, unimplemented = [], []
    for path, (rc, _out, err) in results:
        name = os.path.basename(path)
        if rc == 0:
            continue
        # An argparse rejection is not a failing guard, it is a guard that ADVERTISES a selftest
        # it does not have -- which is worse, because every reader assumes it is proven.
        if rc == 2 and "unrecognized arguments" in err:
            unimplemented.append(name)
        else:
            failed.append(f"{name} (exit {rc})")
    rows.append(Row(GOOD if not failed else BAD, "Guard selftests failing",
                    f"{len(failed)} of {len(scripts)}", "; ".join(failed[:6]),
                    f"for f in {SCRIPTS}/*.py; do python3 $f --selftest; done"))
    advertised = unimplemented + [os.path.basename(m) for m in mentioned_only]
    data_only = sum(1 for f in os.listdir(SCRIPTS)
                    if f.endswith(".py")
                    and os.path.join(SCRIPTS, f) not in scripts
                    and os.path.join(SCRIPTS, f) not in mentioned_only
                    and "--selftest" in open(os.path.join(SCRIPTS, f), encoding="utf-8",
                                             errors="replace").read())
    rows.append(Row(GOOD if not advertised else WARN,
                    "Guards claiming a selftest they do not have",
                    str(len(advertised)),
                    "; ".join(advertised[:6]) or
                    (f"{data_only} more name --selftest in data, not as an offer" if data_only
                     else ""),
                    f"rg -l -- --selftest {SCRIPTS}/*.py"))
    return rows


# --------------------------------------------------------------------------- founder friction

# Words the founder actually uses when something has gone wrong. Measured off his own messages
# in this estate's transcripts, never picked from a thesaurus -- an English word that merely
# SOUNDS negative grades prose rather than frustration (memory:
# a-guard-that-greps-a-word-also-greps-english). Typos are his, and they are load-bearing: he
# types fast when he is annoyed, so the misspellings are part of the signal.
FRICTION = (
    "fuck", "fucck", "fucing", "fucking", "shit", "wtf",
    "whats the point", "what's the point", "whats the fucking point",
    "you keep", "keeps happening", "same nistake", "same mistake",
    "still not", "not working", "doesnt work", "does not work",
    "i said", "i told you", "i asked", "asked you",
    "exhaust", "ehausint", "frustrat", "annoying", "tired of",
    "sorry you", "sorryyou", "why are you", "why is this",
    "black box", "blackbox", "ablack box", "black bes",
    "no progress", "i dont see", "i don't see", "i ont see",
    "hurry", "asap", "too slow", "the loegr", "longer you take",
)


def _epoch(iso: str | None) -> float:
    """An ISO timestamp out of a transcript, as epoch seconds. 0.0 when it will not parse."""
    if not iso:
        return 0.0
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _ago(epoch: float) -> str:
    """Epoch seconds -> `21m ago`. `_age` takes an ISO string; transcripts give us numbers."""
    if not epoch:
        return "undated"
    m = int((time.time() - epoch) / 60)
    return f"{m}m ago" if m < 90 else f"{m // 60}h ago"


def _transcripts(max_age_s: float) -> list[tuple[str, float]]:
    """Every session transcript touched inside the window, newest first."""
    root = os.path.join(HOME, ".claude", "projects")
    now, out = time.time(), []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".jsonl"):
                continue
            path = os.path.join(dirpath, f)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if "subagent" in dirpath:
                continue          # an agent's brief to another agent is not the founder talking
            if now - st.st_mtime <= max_age_s:
                out.append((path, st.st_mtime))
    out.sort(key=lambda t: -t[1])
    return out


def _founder_messages(path: str) -> list[tuple[float, str]]:
    """(epoch, text) for the messages the FOUNDER actually typed in one transcript.

    Everything else in a `type: user` line is machinery wearing the founder's role: tool
    results, hook output, system reminders, the compaction preamble. Counting those as his
    words would report frustration he never expressed, which is the same failure class as a
    guard that grades a proxy.
    """
    out: list[tuple[float, str]] = []
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if '"user"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") != "user" or ev.get("isMeta"):
                    continue
                content = (ev.get("message") or {}).get("content")
                if isinstance(content, list):
                    text = " ".join(b.get("text", "") for b in content
                                    if isinstance(b, dict) and b.get("type") == "text")
                elif isinstance(content, str):
                    text = content
                else:
                    continue                      # a tool_result block is not a founder message
                text = text.strip()
                if not text or text.startswith("<") or text.startswith("["):
                    continue
                if "<system-reminder>" in text or "Caveat:" in text[:80]:
                    continue
                if "[Request interrupted" in text or "This session is being continued" in text:
                    continue
                out.append((_epoch(ev.get("timestamp")), text))
    except OSError:
        pass
    return out


def collect_founder_friction() -> list[Row]:
    """What the founder said, and whether anyone acted on it.

    His words, 2026-08-21: "you need o v across the transctips perdiocially to see the
    founderss frustratios" and "nagaing different agent sessionsis ehausintg". Until this
    ran, every complaint he made lived in ONE session's window and died there -- the session
    that heard it either acted or did not, and no other session, and no later instance of the
    same session after a compaction, ever knew he had said it.

    This reads every transcript on the machine, so a complaint made to any session shows up
    on his page whether or not that session did anything about it.
    """
    files = _transcripts(24 * 3600)
    if not files:
        return [_unknown("Your words in the last 24h", "no transcript touched in 24h",
                         "ls ~/.claude/projects/*/*.jsonl")]

    now = time.time()
    hits: list[tuple[float, str, str]] = []          # (epoch, session, text)
    said = 0
    for path, _mtime in files[:80]:                  # newest 80 transcripts, bounded on purpose
        session = os.path.basename(os.path.dirname(path))[-12:]
        for ts, text in _founder_messages(path):
            if ts and now - ts > 24 * 3600:
                continue
            said += 1
            low = text.lower()
            if any(w in low for w in FRICTION):
                hits.append((ts, session, text))
    hits.sort(key=lambda h: -h[0])

    recent = [h for h in hits if h[0] and now - h[0] <= 6 * 3600]
    state = BAD if recent else (WARN if hits else GOOD)
    rows = [Row(state, "Times you had to complain (24h)",
                f"{len(hits)} of {said} things you said",
                f"{len(recent)} of them in the last 6 hours" if hits
                else "nothing in your own words reads as a complaint",
                "python3 ~/.claude/scripts/founder_board.py --json")]

    for ts, session, text in hits[:5]:
        one = " ".join(text.split())
        rows.append(Row(BAD if now - ts <= 6 * 3600 else WARN,
                        f"— {_ago(ts)}, session {session}",
                        one[:160] + ("…" if len(one) > 160 else ""),
                        "said to one session; no other session could see it until this row existed"))
    return rows


def collect_sessions() -> list[Row]:
    """Every agent session on this machine, on one page.

    His words: "nagaing different agent sessionsis ehausintg" and "the sooner wecan get fouder
    out of loop the btter". Managing them one at a time is the cost this row removes: what each
    one was last told, and how long since it did anything.
    """
    files = _transcripts(2 * 3600)
    if not files:
        return [Row(GOOD, "Agent sessions running", "0", "nothing active in 2 hours",
                    "ls -lt ~/.claude/projects/*/*.jsonl | head")]

    now = time.time()
    live, lines = 0, []
    for path, mtime in files[:20]:
        idle = (now - mtime) / 60.0
        if idle <= 30:
            live += 1
        session = os.path.basename(os.path.dirname(path))[-12:]
        last = ""
        msgs = _founder_messages(path)
        if msgs:
            last = " ".join(msgs[-1][1].split())[:90]
        lines.append(f"{session}: idle {idle:.0f}m — last told: {last or '(nothing typed)'}")

    return [Row(GOOD if live else WARN, "Agent sessions running", str(live),
                " | ".join(lines[:6]) or "none",
                "ls -lt ~/.claude/projects/*/*.jsonl | head")]


def collect_action_items() -> list[Row]:
    """Every action item written down anywhere, counted. Nobody has to read the docs to know.

    His words: "i need a report of acion itens fron this report and tracked and actions ...
    should nt be having to do this, should be auto", "we need to know deliverbles", "and track
    ruthlessly". The items were always written down -- 26 programme docs full of table rows --
    and never counted, so the only way to know what was outstanding was to read them.
    """
    cmd = ["/usr/local/bin/python3", os.path.join(SCRIPTS, "action_items.py"), "--json"]
    # 900, not 300. This collector only parses markdown and measures ~10s idle, but the board's
    # own 12:36 run on 2026-08-21 recorded "timed out after 300s" while the laptop sat at load
    # 400. A timeout tuned to an idle machine turns a working collector into UNKNOWN exactly
    # when the founder most wants the number -- and UNKNOWN reads as "nobody counted".
    rc, out, err = sh(cmd, 900)
    if rc != 0 or not out.strip():
        return [_unknown("Action items outstanding", err.strip()[:200] or f"exit {rc}",
                         " ".join(cmd))]
    try:
        d = json.loads(out)
    except json.JSONDecodeError as e:
        return [_unknown("Action items outstanding", f"printed no JSON: {e}", " ".join(cmd))]

    items = d.get("items") or []
    open_n, done_n, unk = d.get("open", 0), d.get("done", 0), d.get("unknown", 0)
    untracked = d.get("untracked", 0)
    graded = open_n + done_n
    rows = [Row(BAD if open_n > done_n else GOOD, "Action items outstanding",
                f"{open_n} open, {done_n} done",
                f"across {d.get('docs', 0)} docs on {d.get('ref', '?')}; "
                f"{done_n / graded * 100:.0f}% of what we wrote down is finished"
                if graded else "nothing graded",
                " ".join(cmd))]
    # An item whose status cell matches no vocabulary is NOT counted as done and NOT hidden.
    rows.append(Row(WARN if unk else GOOD, "Items with no readable status", str(unk),
                    "the table HAS a status column and the word in it is one nothing here "
                    "knows -- fixable in action_items.py",
                    " ".join(cmd)))
    # Counted apart from the row above because the FIX is apart, and reporting one number hid
    # that. His words 2026-08-21: "e need to strt tagging ad ncategorissing, project anagent
    # hygene". Until 2026-08-21 both of these were one figure of 689, which read as one
    # backlog; 574 of them needed an edit to a DOCUMENT and 115 needed an edit to a SCRIPT.
    worst = collections.Counter(i.get("source", "?") for i in items
                                if i.get("state") == "untracked").most_common(3)
    rows.append(Row(WARN if untracked else GOOD, "Deliverables no document can mark done",
                    str(untracked),
                    ("worst: " + ", ".join(f"{s.replace('docs/', '')} ({n})" for s, n in worst)
                     + " -- these tables have no status column at all, so nothing can ever "
                       "report them finished") if worst else "every table has a status column",
                    " ".join(cmd)))
    stale = sorted((i for i in items if i.get("state") == "open"),
                   key=lambda i: -(i.get("age_days") or 0))[:4]
    for i in stale:
        rows.append(Row(WARN, f"— {i.get('id')} open {i.get('age_days', 0):.0f}d",
                        str(i.get("title", ""))[:110],
                        f"{i.get('source')}:{i.get('line')}"))
    return rows


def collect_time_and_mistakes() -> list[Row]:
    """How long the work takes, and how often it is wrong. Both, on his page, unasked.

    His words, 2026-08-21: "too nay bugs", "and having to renid to test thorough", "lso he tinne
    takenninstakes nade etc", "we need it auo".

    The estate had no number for either. Every session reported the thing it shipped and none of
    them reported how many attempts it took or how long it sat, so "too many bugs" was a feeling
    he had to defend rather than a figure anyone could check.

    A red CI run is the estate's cheapest, most honest mistake counter: it is a change that was
    pushed believing it worked and did not.
    """
    rows: list[Row] = []
    runs = _gh_runs("", limit=100)
    if runs is None:
        rows.append(_unknown("Pushes that were wrong (last 100 runs)", "gh run list failed",
                             "gh run list --limit 100"))
    else:
        done = [r for r in runs if r.get("conclusion")]
        bad = [r for r in done if r["conclusion"] in ("failure", "timed_out", "cancelled")]
        pct = (len(bad) / len(done) * 100) if done else 0.0
        rows.append(Row(BAD if pct > 25 else (WARN if pct > 10 else GOOD),
                        "Pushes that were wrong", f"{len(bad)} of {len(done)} CI runs red",
                        f"{pct:.0f}% of everything pushed did not work first time",
                        "gh run list --limit 100 --json conclusion"))

    rc, out, err = sh(["gh", "pr", "list", "--repo", GH_REPO, "--state", "merged", "--limit", "20",
                       "--json", "number,title,createdAt,mergedAt"], 90)
    if rc != 0 or not out.strip():
        rows.append(_unknown("How long work sits before it lands", err.strip()[:160] or f"exit {rc}",
                             "gh pr list --state merged --limit 20"))
        return rows
    try:
        prs = json.loads(out)
    except json.JSONDecodeError as e:
        rows.append(_unknown("How long work sits before it lands", f"no JSON: {e}", ""))
        return rows

    flat = []
    for pr in prs:
        a, b = _epoch(pr.get("createdAt")), _epoch(pr.get("mergedAt"))
        if a and b and b >= a:
            flat.append((b - a) / 3600.0)
    flat.sort()
    if flat:
        mid = flat[len(flat) // 2]
        worst = flat[-1]
        rows.append(Row(BAD if mid > 6 else (WARN if mid > 2 else GOOD),
                        "How long work sits before it lands",
                        f"{mid:.1f}h median, {worst:.1f}h worst",
                        f"over the last {len(flat)} merged pull requests",
                        "gh pr list --state merged --limit 20 --json createdAt,mergedAt"))
    else:
        rows.append(_unknown("How long work sits before it lands", "no merged PR had both dates",
                             "gh pr list --state merged --limit 20"))
    return rows


COLLECTORS = [
    ("Money", collect_spend),
    ("What you said, and whether it landed", collect_founder_friction),
    ("Work in flight", collect_prs),
    ("What is broken", collect_estate_checks),
    ("The machine that runs itself", collect_launchd),
    ("Agent sessions", collect_sessions),
    ("Shipped — is it live?", collect_shipped_to_live),
    ("The guards themselves", collect_hooks_and_guards),
    ("Time taken, and mistakes made", collect_time_and_mistakes),
    ("Deliverables", collect_action_items),
    ("What was asked for", collect_requirements),
    ("Waiting on you", collect_founder_decisions),
]


def build() -> dict:
    sections = []
    for title, fn in COLLECTORS:
        started = time.time()
        try:
            rows = fn()
        except Exception as e:                    # noqa: BLE001 -- rule 1: never report zero
            rows = [_unknown(title, f"collector raised {type(e).__name__}: {e}")]
        sections.append({"title": title, "took_s": round(time.time() - started, 1),
                         "rows": [r.as_dict() for r in rows]})
    flat = [r for s in sections for r in s["rows"]]
    return {
        "generated_at": time.time(),
        "sections": sections,
        "bad": sum(1 for r in flat if r["state"] == BAD),
        "unknown": sum(1 for r in flat if r["state"] == UNKNOWN),
    }


# --------------------------------------------------------------------------- rendering

def render_text(board: dict) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(board["generated_at"]))
    mark = {GOOD: "  ok  ", BAD: " FAIL ", WARN: " warn ", UNKNOWN: "  ??  "}
    out = [f"FOUNDER BOARD — {stamp}",
           f"{board['bad']} failing, {board['unknown']} could not be measured", ""]
    for s in board["sections"]:
        out.append(f"=== {s['title']} ({s['took_s']}s) ===")
        for r in s["rows"]:
            out.append(f"[{mark[r['state']]}] {r['label'][:56]:<56} {r['value']}")
            if r["detail"]:
                out.append(f"           {r['detail'][:100]}")
        out.append("")
    return "\n".join(out)


def _atomic_write(path: str, text: str) -> None:
    """Write text so a reader never sees a half-written file.

    Two reasons, both measured on 2026-08-21. The hourly launchd board run and a
    session's manual run overlapped for 50 minutes on this laptop, and both had
    `open(path, "w")`, which TRUNCATES first -- so the founder opening the page
    mid-write gets a file that is empty or cut in half. And the disk was 100%
    full, where a direct write dies part-way and destroys the last good board.
    Writing beside the target and renaming leaves the previous board in place on
    either failure; os.replace is atomic within one filesystem.
    """
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def render_html(board: dict) -> str:
    e = html.escape
    stamp = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(board["generated_at"]))
    headline = ("Everything measured is green." if not board["bad"]
                else f"{board['bad']} thing{'s' if board['bad'] != 1 else ''} broken.")
    n = board["unknown"]
    # An unmeasured row is not a green row. It is said out loud, at the top, in words.
    unmeasured = "" if not n else f" {n} thing{'s' if n != 1 else ''} could not be measured."
    parts = ["<title>Founder Board</title>", _CSS,
             f'<header><p class="eyebrow">Estate status</p><h1>{e(headline)}</h1>'
             f'<p class="stamp">Measured {e(stamp)}. Every row below is a command, not a claim.'
             f'{unmeasured}</p></header>',
             "<main>"]
    for s in board["sections"]:
        parts.append(f'<section><h2>{e(s["title"])}</h2><ul class="rows">')
        for r in s["rows"]:
            parts.append(
                f'<li class="row {r["state"]}"><span class="label">{e(r["label"])}</span>'
                f'<span class="value">{e(str(r["value"]))}</span>'
                + (f'<span class="detail">{e(r["detail"])}</span>' if r["detail"] else "")
                + (f'<code>{e(r["command"])}</code>' if r["command"] else "")
                + "</li>")
        parts.append("</ul></section>")
    parts.append("</main>")
    return "\n".join(parts)


_CSS = """<style>
:root{--bg:#fbfaf8;--ink:#1b1a18;--dim:#6c6862;--line:#e3ded6;--card:#ffffff;
--good:#2f7d51;--bad:#b3261e;--warn:#9a6b00;--unk:#5b5f6b;--accent:#1b4d7a;}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--bg:#15161a;--ink:#eceae6;--dim:#9a968f;--line:#2c2e35;--card:#1c1e23;
--good:#6ec48d;--bad:#ff8a80;--warn:#e0b352;--unk:#9aa0ae;--accent:#7fb3e0;}}
:root[data-theme="dark"]{--bg:#15161a;--ink:#eceae6;--dim:#9a968f;--line:#2c2e35;--card:#1c1e23;
--good:#6ec48d;--bad:#ff8a80;--warn:#e0b352;--unk:#9aa0ae;--accent:#7fb3e0;}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;padding:2rem 1.25rem 4rem;
font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;}
header,main{max-width:62rem;margin:0 auto}
.eyebrow{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin:0}
h1{font-size:clamp(1.6rem,5vw,2.4rem);margin:.3rem 0 .5rem;text-wrap:balance;letter-spacing:-.02em}
.stamp{color:var(--dim);font-size:.9rem;margin:0 0 2rem}
h2{font-size:.8rem;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);
margin:2rem 0 .6rem;font-weight:600}
.rows{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.4rem}
.row{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--unk);
border-radius:6px;padding:.7rem .9rem;display:grid;grid-template-columns:1fr auto;gap:.2rem .9rem}
.row.good{border-left-color:var(--good)}.row.bad{border-left-color:var(--bad)}
.row.warn{border-left-color:var(--warn)}.row.unknown{border-left-color:var(--unk)}
.label{font-weight:550}
.value{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.row.bad .value{color:var(--bad)}.row.good .value{color:var(--good)}
.row.warn .value{color:var(--warn)}.row.unknown .value{color:var(--unk)}
.detail{grid-column:1/-1;color:var(--dim);font-size:.87rem}
code{grid-column:1/-1;color:var(--dim);font-size:.76rem;font-family:ui-monospace,Menlo,monospace;
overflow-x:auto;white-space:pre;display:block;opacity:.75}
@media(max-width:34rem){.row{grid-template-columns:1fr}.value{text-align:left}}
</style>"""


# --------------------------------------------------------------------------- selftest

def selftest() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        if not cond:
            print(f"FAIL: {name}")
            ok = False

    # RULE 1: a collector that raises must produce UNKNOWN, never an empty green section.
    def boom():
        raise RuntimeError("probe is dead")
    saved = COLLECTORS[:]
    COLLECTORS[:] = [("Broken probe", boom)]
    b = build()
    COLLECTORS[:] = saved
    rows = b["sections"][0]["rows"]
    check("a raising collector yields exactly one row", len(rows) == 1)
    check("a raising collector reports UNKNOWN", rows[0]["state"] == UNKNOWN)
    check("a raising collector is not counted as good", b["unknown"] == 1 and b["bad"] == 0)
    check("the reason survives", "probe is dead" in rows[0]["detail"])

    # A QUEUED or IN_PROGRESS check is not a red check. This is graded directly because the
    # first draft got it wrong on a live PR.
    red, pending = classify_checks([
        {"name": "changes", "status": "QUEUED", "conclusion": ""},
        {"name": "keep", "status": "IN_PROGRESS", "conclusion": ""},
        {"name": "guard", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"context": "legacy", "conclusion": None},
        {"name": "python", "status": "COMPLETED", "conclusion": "FAILURE"},
        {"name": "skipped-lane", "status": "COMPLETED", "conclusion": "SKIPPED"},
    ])
    check("a running check is not reported red", red == ["python"])
    check("a running check is counted as pending", pending == 3)

    # A half-written board is worse than a stale one. Two board processes overlapped
    # for 50 minutes on 2026-08-21 and the disk was full; `open(path, "w")` truncates
    # before it writes, so either one leaves the founder looking at a cut-off page.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        target = os.path.join(td, "board.html")
        _atomic_write(target, "OLD")
        _atomic_write(target, "NEW")
        check("an atomic write replaces the content", open(target).read() == "NEW")
        failed = False
        try:
            _atomic_write(target, {"not": "a string"})  # type: ignore[arg-type]
        except (TypeError, AttributeError):
            failed = True
        check("a failing write raises", failed)
        check("a failing write leaves the previous board intact",
              open(target).read() == "NEW")
        check("a failing write leaves no .tmp behind",
              not os.path.exists(target + ".tmp"))

    # RULE 3: every row carries when it was measured.
    check("rows are timestamped", all(r["measured_at"] > 0
                                      for s in b["sections"] for r in s["rows"]))

    # A timeout is reported as a timeout, not as a zero.
    rc, _, err = sh(["/bin/sleep", "5"], 1)
    check("sh reports a timeout as 124", rc == 124 and "timed out" in err)
    rc, _, err = sh(["/definitely/not/a/binary"], 5)
    check("sh reports an unspawnable command", rc == 127 and err)

    # The launchd case, graded directly. This is the defect that made 8 rows on the live page
    # read UNKNOWN on 2026-08-21: launchd's PATH has no /usr/local/bin, so `gh` was missing
    # for the only caller that matters. Mutating tool_path() back to os.environ["PATH"] makes
    # this fail.
    saved_path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"      # exactly what launchd gives
        # Installed-ness is decided against the caller's REAL PATH, never against
        # tool_path(). Asking the function under test whether to run the test is how a first
        # draft of this check passed a mutant that broke tool_path() outright.
        if shutil.which("gh", path=saved_path):
            rc, out, err = sh(["gh", "--version"], 20)
            check("gh runs under launchd's PATH", rc == 0 and "gh version" in out)
        else:
            # Reported, never dropped: an allow-list whose miss case is silent is how ten
            # findings were lost in eighteen hours on this estate.
            print("NOTE: gh is not installed anywhere in _TOOL_DIRS; the launchd PATH case "
                  "could not be graded on this machine.")
    finally:
        os.environ["PATH"] = saved_path

    # The renderers must survive every state, including UNKNOWN with no command.
    fake = {"generated_at": time.time(), "bad": 1, "unknown": 1, "sections": [
        {"title": "T", "took_s": 0.0, "rows": [
            Row(GOOD, "g", "1").as_dict(), Row(BAD, "b<&>", "2", "d", "c").as_dict(),
            Row(WARN, "w", "3").as_dict(), _unknown("u", "why").as_dict()]}]}
    txt, page = render_text(fake), render_html(fake)
    check("text render mentions every row", all(k in txt for k in ("g", "w", "u")))
    check("html escapes the label", "b&lt;&amp;&gt;" in page)
    check("html defines colours on bare :root", ":root{--bg:" in page)
    check("html paints the body background", "body{background:var(--bg)" in page)

    print("PASS: a dead collector reports UNKNOWN, never zero." if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", metavar="PATH")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    board = build()
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        _atomic_write(STATE, json.dumps(board, indent=2))
    except OSError as e:
        print(f"[board] could not save state: {e}", file=sys.stderr)

    if args.html:
        _atomic_write(args.html, render_html(board))
        # stderr, never stdout. `--json --html X` together put this line ABOVE the JSON
        # document, so json.load() on the captured stdout died at "Expecting value:
        # line 1 column 1". Measured 2026-08-21. A status line is not part of the payload.
        print(f"wrote {args.html}", file=sys.stderr)
    if args.json:
        print(json.dumps(board, indent=2))
    elif not args.html:
        print(render_text(board))
    return 1 if board["bad"] else 0


if __name__ == "__main__":
    sys.exit(main())
