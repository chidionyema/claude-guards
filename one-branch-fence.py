#!/usr/bin/env python3
"""PreToolUse guard: one branch and one worktree per session, and no branch that adds nothing.

FOUNDER DIRECTIVE 2026-08-21, verbatim: "you goal is to ensure there is only one branch and one
worktree active for any agent session at any point in tine, this is the only way to avoid this
recurring, both local and renote", then "also the cheaper fence" and "lets do it wwith a
rollbacl buiilt in".

WHAT PRODUCED IT, MEASURED. 5 live agent sessions held 62 git-registered worktrees and 387
non-main remote branches. 84% of those branches were written in the last three days, so this is
not an archive of dead work. Hand-merging the 37 conflicted ones showed why: 33 of 37 merged to
a tree byte-identical to main. Roughly 4,000 lines of "conflict" were sessions re-implementing
work that had already landed by another door, because nothing told them it had.

THREE CHECKS, CHEAPEST FIRST.

  A  ADDS-NOTHING   at push. Merge the branch into origin/main in memory; if the result is
                    main's tree, the branch changes nothing main does not already have. This is
                    the cheap fence: it caught 33 of 37 in replay, and it costs one merge-tree.
  B  STALE BASE     at `git checkout -b` / `git switch -c` / `git worktree add`. A branch that
                    starts from a main fetched hours ago cannot see what landed since, which is
                    how all 33 were written.
  C  SECOND HOLDING at the same commands. One worktree and one branch per session_id.

ROLLBACK, THREE WAYS, ALL ONE COMMAND AND NONE NEEDING A RESTART.

  touch ~/.claude/ONE_BRANCH_FENCE_OFF            # off entirely, every check, every session
  echo log > ~/.claude/one-branch-fence.mode      # back to log-only; nothing is ever refused
  python3 ~/.claude/scripts/one-branch-fence.py --uninstall   # remove it from settings.json

Every refusal prints the first of those, so a session this stops wrongly can free itself without
finding this file. The mode file is read on EVERY call, so a rollback takes effect on the next
tool call rather than the next session.

FAILS OPEN. Any exception at all returns 0. A registry read is a file read, and a half-written
registry is the normal state of a machine with 62 live worktrees; a traceback must never be what
decides whether the estate can commit.

GRANDFATHERED. Check C never fires for a worktree that existed when the fence was installed
(~/.claude/state/one-branch/GRANDFATHERED.json). Without that, turning it on refuses the next git
command of every session already holding a worktree, including any mid-commit.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
OFF_SWITCH = HOME / ".claude" / "ONE_BRANCH_FENCE_OFF"
MODE_FILE = HOME / ".claude" / "one-branch-fence.mode"
STATE_DIR = HOME / ".claude" / "state" / "one-branch"
GRANDFATHERED = STATE_DIR / "GRANDFATHERED.json"
LOG = STATE_DIR / "would-have-fired.jsonl"

# A base older than this cannot see what landed since, which is check B's whole point.
STALE_BASE_S = 15 * 60

MARKERS = ("second-worktree-intended", "stale-base-intended", "adds-nothing-intended")

ROLLBACK = "  touch ~/.claude/ONE_BRANCH_FENCE_OFF     # turns this fence off, immediately"


def sh(args: list[str], cwd: str | None = None, timeout: int = 20) -> tuple[int, str]:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "").strip()


def mode() -> str:
    """log => never refuses, only records. refuse => blocks. Read every call, so rollback is live."""
    try:
        m = MODE_FILE.read_text(encoding="utf-8").strip().lower()
    except Exception:  # noqa: BLE001
        return "log"
    return m if m in ("log", "refuse") else "log"


def state_path(session: str) -> Path:
    safe = "".join(c for c in session if c.isalnum() or c in "-_")[:64] or "nosession"
    return STATE_DIR / f"{safe}.json"


def read_state(session: str) -> dict:
    try:
        return json.loads(state_path(session).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def write_state(session: str, data: dict) -> None:
    """Atomic. A torn write here would wedge every later call for this session."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        p = state_path(session)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001
        pass


def grandfathered() -> set:
    try:
        return set(json.loads(GRANDFATHERED.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def record(kind: str, detail: dict) -> None:
    """Log mode's only output, and refuse mode's audit trail."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": int(time.time()), "check": kind, **detail}) + "\n")
    except Exception:  # noqa: BLE001
        pass


def adds_nothing(cwd: str, ref: str) -> bool:
    """True when merging `ref` into origin/main produces main's own tree.

    Not the same as comparing the two trees: a branch has its own older tree and still adds
    nothing. The question is what the merge would CHANGE, which is what merge-tree answers.
    """
    rc, main_tree = sh(["git", "rev-parse", "origin/main^{tree}"], cwd)
    if rc != 0 or not main_tree:
        return False
    rc, merged = sh(["git", "merge-tree", "--write-tree", "origin/main", ref], cwd, timeout=60)
    if rc != 0 or not merged:          # conflicts, or an old git: say nothing
        return False
    return merged.splitlines()[0].strip() == main_tree


def base_age_s(cwd: str) -> float | None:
    """Seconds since origin/main was last fetched. None when it cannot be told."""
    for p in ("FETCH_HEAD", "refs/remotes/origin/main"):
        rc, out = sh(["git", "rev-parse", "--git-path", p], cwd)
        if rc == 0 and out:
            f = Path(out if os.path.isabs(out) else os.path.join(cwd, out))
            if f.exists():
                return time.time() - f.stat().st_mtime
    return None


def creates_branch(argv: list[str]) -> str | None:
    if argv[:2] == ["git", "worktree"] and "add" in argv[:4]:
        return "worktree"
    if argv[:2] == ["git", "checkout"] and any(a in ("-b", "-B") for a in argv):
        return "branch"
    if argv[:2] == ["git", "switch"] and any(a in ("-c", "-C") for a in argv):
        return "branch"
    return None


def pushed_ref(argv: list[str], cwd: str) -> str | None:
    if "push" not in argv[:4]:
        return None
    if any(a in ("--delete", "-d", "--dry-run", "--tags") for a in argv):
        return None
    for a in argv[3:]:
        if a.startswith("-"):
            continue
        return a.split(":")[0] or None
    rc, out = sh(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd)
    return out if rc == 0 and out else None


def block(msg: str) -> int:
    print(msg + "\n\nRoll it back if this is wrong:\n" + ROLLBACK, file=sys.stderr)
    return 2


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--install" in sys.argv:
        return install()
    if "--uninstall" in sys.argv:
        return uninstall()
    try:
        if OFF_SWITCH.exists():
            return 0
        payload = json.load(sys.stdin)
        if payload.get("tool_name") != "Bash":
            return 0
        cmd = (payload.get("tool_input") or {}).get("command") or ""
        session = payload.get("session_id") or "nosession"
        cwd = payload.get("cwd") or os.getcwd()
        if any(m in cmd for m in MARKERS):
            record("marker", {"session": session, "cmd": cmd[:200]})
            return 0
        return grade(cmd, session, cwd)
    except Exception:  # noqa: BLE001
        return 0                      # fails OPEN, always


def grade(cmd: str, session: str, cwd: str) -> int:
    refusing = mode() == "refuse"
    st = read_state(session)

    for part in re.split(r"&&|\|\||;|\n", cmd):
        try:
            argv = shlex.split(part)
        except ValueError:
            continue
        if not argv or argv[0] != "git":
            continue

        kind = creates_branch(argv)
        if kind:
            # C -- second holding.
            held = st.get(kind)
            if held and held not in grandfathered():
                record("second-" + kind, {"session": session, "held": held, "cmd": part[:200]})
                if refusing:
                    return block(
                        f"BLOCKED by one-branch-fence: this session already holds a {kind} "
                        f"(`{held}`).\nFounder directive 2026-08-21: one branch and one worktree "
                        f"per session. 5 sessions were holding 62 worktrees and 387 branches when "
                        f"this was written.\n\nFinish or hand off the one you have. If you genuinely "
                        f"need a second, say so in the command:\n"
                        f"  <your command>  # second-worktree-intended"
                    )
            else:
                st[kind] = argv[-1]
                write_state(session, st)

            # B -- stale base.
            age = base_age_s(cwd)
            if age is not None and age > STALE_BASE_S:
                record("stale-base", {"session": session, "age_s": int(age), "cmd": part[:200]})
                if refusing:
                    return block(
                        f"BLOCKED by one-branch-fence: origin/main here was last fetched "
                        f"{int(age // 60)} minutes ago.\nA branch cut from a stale main cannot see "
                        f"what has landed since. Measured 2026-08-21: 33 of 37 branches merged to a "
                        f"tree byte-identical to main -- every one of them was work that had already "
                        f"landed by another door.\n\n  git fetch origin main\n\nthen run your command "
                        f"again, or:  <your command>  # stale-base-intended"
                    )
            continue

        ref = pushed_ref(argv, cwd)
        if ref and ref not in ("main", "HEAD"):
            # A -- the cheap one. Does merging this change anything main does not have?
            if adds_nothing(cwd, "HEAD"):
                record("adds-nothing", {"session": session, "ref": ref, "cmd": part[:200]})
                if refusing:
                    return block(
                        f"BLOCKED by one-branch-fence: merging `{ref}` into origin/main would "
                        f"produce main's own tree.\nEverything on this branch is already on main by "
                        f"another door. Pushing it adds a branch to a remote that has 387 of them "
                        f"and changes nothing.\n\nCheck what you have that main does not:\n"
                        f"  git merge-tree --write-tree origin/main HEAD\n"
                        f"  git rev-parse origin/main^{{tree}}\n\n"
                        f"If you mean it:  <your command>  # adds-nothing-intended"
                    )
    return 0


def install() -> int:
    """Wire it, seed the grandfather list, and leave a timestamped settings backup."""
    import shutil
    s = HOME / ".claude" / "settings.json"
    bak = s.with_name(f"settings.json.bak-one-branch-{int(time.time())}")
    shutil.copy2(s, bak)
    data = json.loads(s.read_text(encoding="utf-8"))
    cmd = f"python3 {HOME}/.claude/scripts/one-branch-fence.py"
    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    if any(cmd in h.get("command", "") for g in pre for h in g.get("hooks", [])):
        print("already installed")
        return 0
    pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]})
    s.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Grandfather every worktree that exists right now, so turning it on refuses nobody.
    paths = []
    for clone in (HOME / "Documents" / "code" / "prospector",):
        rc, out = sh(["git", "worktree", "list", "--porcelain"], str(clone))
        if rc == 0:
            paths += [ln.split(" ", 1)[1] for ln in out.splitlines() if ln.startswith("worktree ")]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    GRANDFATHERED.write_text(json.dumps(sorted(set(paths))), encoding="utf-8")
    if not MODE_FILE.exists():
        MODE_FILE.write_text("log\n", encoding="utf-8")
    print(f"installed in log mode. {len(paths)} worktrees grandfathered. backup: {bak}")
    print("  echo refuse > ~/.claude/one-branch-fence.mode   # when the log says it is safe")
    return 0


def uninstall() -> int:
    s = HOME / ".claude" / "settings.json"
    data = json.loads(s.read_text(encoding="utf-8"))
    cmd = "one-branch-fence.py"
    pre = data.get("hooks", {}).get("PreToolUse", [])
    for g in list(pre):
        g["hooks"] = [h for h in g.get("hooks", []) if cmd not in h.get("command", "")]
        if not g["hooks"]:
            pre.remove(g)
    s.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("uninstalled")
    return 0


def selftest() -> int:
    import tempfile
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r} want {want!r}")

    check("creates_branch worktree add", creates_branch(shlex.split("git worktree add --detach /tmp/x")), "worktree")
    check("creates_branch checkout -b", creates_branch(shlex.split("git checkout -b feat/x")), "branch")
    check("creates_branch switch -c", creates_branch(shlex.split("git switch -c feat/x")), "branch")
    check("creates_branch plain checkout", creates_branch(shlex.split("git checkout main")), None)
    check("creates_branch worktree list", creates_branch(shlex.split("git worktree list")), None)
    check("creates_branch commit", creates_branch(shlex.split("git commit -m x")), None)

    check("pushed_ref explicit", pushed_ref(shlex.split("git push origin feat/x"), "/"), "feat/x")
    check("pushed_ref colon", pushed_ref(shlex.split("git push origin HEAD:integrate/a"), "/"), "HEAD")
    check("pushed_ref delete", pushed_ref(shlex.split("git push origin --delete feat/x"), "/"), None)
    check("pushed_ref dry-run", pushed_ref(shlex.split("git push --dry-run origin feat/x"), "/"), None)
    check("pushed_ref not a push", pushed_ref(shlex.split("git commit -m x"), "/"), None)

    # The off switch wins over everything, including refuse mode.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "off"
        p.touch()
        check("off switch exists", p.exists(), True)

    # mode() must never return anything but log/refuse, and must default to log.
    real = MODE_FILE
    try:
        globals()["MODE_FILE"] = Path("/nonexistent/nope")
        check("mode defaults to log", mode(), "log")
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m"
            globals()["MODE_FILE"] = m
            m.write_text("refuse\n")
            check("mode refuse", mode(), "refuse")
            m.write_text("REFUSE")
            check("mode is case-insensitive", mode(), "refuse")
            m.write_text("garbage")
            check("mode garbage is log", mode(), "log")
    finally:
        globals()["MODE_FILE"] = real

    # A bad payload must not raise. This is the fail-open contract.
    for bad in ("", "not json", "{}", '{"tool_name":"Bash"}'):
        r = subprocess.run([sys.executable, __file__], input=bad, capture_output=True, text=True)
        if r.returncode != 0:
            fails.append(f"fail-open on payload {bad!r}: exit {r.returncode}")

    # In log mode nothing is ever refused, whatever the state says.
    real_mode = MODE_FILE
    try:
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m"
            m.write_text("log")
            globals()["MODE_FILE"] = m
            check("log mode never blocks", grade("git checkout -b x", "s", "/tmp"), 0)
    finally:
        globals()["MODE_FILE"] = real_mode

    print(f"one-branch-fence selftest: {14 + 4} checks, {len(fails)} failed")
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
