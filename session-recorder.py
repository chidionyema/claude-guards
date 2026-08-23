#!/usr/bin/env python3
"""Write a recovery file after every turn, so a dead session loses nothing.

Founder, 2026-08-21: "this is a problen, session dies and all ccontet lost".

WHAT WAS ACTUALLY WRONG. The context is not lost. It is on disk the whole time --
~/.claude/projects/<slug>/<session-id>.jsonl holds every founder turn verbatim and every tool
call. What was missing is anything that reads it back. `checkpoints/LATEST.md` only exists when
an agent remembers to write one, and an agent that is about to be compacted or hard-killed is
exactly the agent that does not.

Three ways a session dies, and only one of them gives any warning:
  compaction   PostCompact fires, but the window is already gone
  /clear       no warning
  kill -9, reboot, laptop wedge   no warning at all

So this runs on Stop -- after every single turn -- and rebuilds the recovery file from the
transcript. The file is never more than one turn stale, and it survives all three.

  session-recorder.py --hook          what settings.json runs (reads hook json on stdin)
  session-recorder.py --restore       print the newest recovery file for this project
  session-recorder.py --list          every recorded session, newest first
  session-recorder.py --selftest      prove it
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
MAX_TURNS = 40          # founder turns kept verbatim
MAX_FILES = 40
MAX_CMDS = 25
# A "founder turn" is something a person typed. Everything else that arrives on the user
# channel -- hook feedback, tool denials, system reminders, the compaction preamble -- is
# machinery talking to the agent, and it buries the real asks if it is kept.
SKIP_PREFIXES = (
    "<", "[SYSTEM", "Caveat:", "This session is being continued",
    "Stop hook feedback", "PreToolUse:", "PostToolUse:", "UserPromptSubmit:",
    "[Request interrupted", "API Error", "Tool ran without output",
    "The user doesn't want to proceed", "[Cross-session",
)


def _slug(cwd: str) -> str:
    return "-" + re.sub(r"[^A-Za-z0-9]", "-", cwd).lstrip("-")


def _text_blocks(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [c["text"] for c in content if isinstance(c, dict) and c.get("type") == "text"]
    return []


def harvest(transcript: Path) -> dict:
    """Pull the four things LAW 16 asks for out of a transcript, mechanically."""
    turns: list[str] = []
    files: list[str] = []
    cmds: list[str] = []
    last_reply = ""
    n_tools = 0

    with transcript.open(errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message") or {}
            content = msg.get("content")

            # A message typed while a turn is RUNNING is not a `user` row at all. It lands
            # as queue-operation/enqueue and fires no UserPromptSubmit. Measured on this
            # estate's own transcripts; prompt-ledger.py:1 records the same finding. Miss
            # these and you lose exactly the messages the founder sent while waiting.
            if d.get("type") == "queue-operation" and d.get("operation") == "enqueue":
                for key in ("prompt", "content", "text", "value"):
                    v = d.get(key)
                    if isinstance(v, str) and v.strip():
                        s_ = v.strip()
                        if not s_.startswith(SKIP_PREFIXES):
                            turns.append(s_)
                        break
                continue

            if d.get("type") == "user":
                for t in _text_blocks(content):
                    s = t.strip()
                    if s and not s.startswith(SKIP_PREFIXES):
                        turns.append(s)

            elif d.get("type") == "assistant" and isinstance(content, list):
                for c in content:
                    if c.get("type") == "text" and c.get("text", "").strip():
                        last_reply = c["text"].strip()
                    elif c.get("type") == "tool_use":
                        n_tools += 1
                        name, inp = c.get("name"), c.get("input") or {}
                        if name in ("Write", "Edit", "NotebookEdit"):
                            p = inp.get("file_path")
                            if p and p not in files:
                                files.append(p)
                        elif name == "Bash":
                            cmd = (inp.get("command") or "").strip()
                            if cmd:
                                cmds.append(cmd.splitlines()[0][:160])
                                # files a heredoc or redirect created, which Bash-only
                                # sessions would otherwise never record
                                for m in re.finditer(r"(?:>|>>|cat\s*>\s*)\s*(\S+\.(?:py|md|json|ya?ml|sh|ts|tsx|js|css))", cmd):
                                    f = m.group(1)
                                    if f not in files:
                                        files.append(f)

    return {
        "turns": turns[-MAX_TURNS:],
        "turns_total": len(turns),
        "files": files[-MAX_FILES:],
        "cmds": cmds[-MAX_CMDS:],
        "last_reply": last_reply,
        "n_tools": n_tools,
    }


def _git(cwd: str) -> list[str]:
    out = []
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain=v1", "-b"],
            capture_output=True, text=True, timeout=8,
        )
        if r.returncode == 0:
            lines = r.stdout.splitlines()
            if lines:
                out.append(lines[0].removeprefix("## "))
            dirty = [l for l in lines[1:] if l[:2] != "??"]
            if dirty:
                out.append(f"{len(dirty)} tracked file(s) modified and not committed")
                out.extend("  " + l for l in dirty[:10])
    except Exception:
        pass
    return out


def render(h: dict, session_id: str, cwd: str) -> str:
    L = [
        f"# SESSION RECOVERY — {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Written automatically after every turn. If a session was compacted, cleared, killed or",
        "lost to a reboot, this is what it was doing. Nothing here was typed by an agent.",
        "",
        f"- session: `{session_id}`",
        f"- cwd: `{cwd}`",
        f"- transcript: `{PROJECTS / _slug(cwd) / (session_id + '.jsonl')}`",
        f"- {h['turns_total']} founder turns, {h['n_tools']} tool calls",
        "",
        "## WHAT THE FOUNDER ASKED, verbatim, in order",
        "",
    ]
    start = max(0, h["turns_total"] - len(h["turns"]))
    if start:
        L.append(f"_(earlier {start} turns are in the transcript above)_")
        L.append("")
    for i, t in enumerate(h["turns"], start=start + 1):
        body = t if len(t) <= 600 else t[:600] + " …"
        L.append(f"{i}. " + body.replace("\n", "\n   "))
    L += ["", "## WHERE IT GOT TO — the last thing the session said", ""]
    lr = h["last_reply"]
    L.append("_(no reply recorded yet)_" if not lr else "> " + (lr if len(lr) <= 1800 else lr[:1800] + " …").replace("\n", "\n> "))
    L += ["", "## FILES THIS SESSION WROTE", ""]
    L += [f"- `{f}`" for f in h["files"]] or ["_(none)_"]
    L += ["", "## LAST COMMANDS", "", "```"] + (h["cmds"] or ["(none)"]) + ["```"]
    g = _git(cwd)
    if g:
        L += ["", "## GIT AT THE MOMENT OF WRITING", "", "```"] + g + ["```"]
    L += ["", "## HOW TO PICK THIS UP", "",
          "Read the turns above in order. The last one is the live question. Then open the",
          "transcript for anything this summary cut."]
    return "\n".join(L) + "\n"


def record(transcript: Path, session_id: str, cwd: str) -> Path:
    h = harvest(transcript)
    d = PROJECTS / _slug(cwd) / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    body = render(h, session_id, cwd)
    per = d / f"RECOVERY-{session_id[:8]}.md"
    tmp = per.with_suffix(".tmp")
    tmp.write_text(body)
    os.replace(tmp, per)                      # atomic: a reboot never leaves half a file
    latest = d / "RECOVERY-LATEST.md"
    tmp2 = d / ".RECOVERY-LATEST.tmp"
    tmp2.write_text(body)
    os.replace(tmp2, latest)
    return per


def cmd_hook() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0                              # never block a turn
    t = payload.get("transcript_path")
    if not t or not Path(t).exists():
        return 0
    try:
        record(Path(t), payload.get("session_id", "unknown"), payload.get("cwd") or os.getcwd())
    except Exception as exc:
        # A recorder that breaks a turn is worse than none, so this still returns 0.
        # But a recorder that fails SILENTLY is worse than both: it is a recovery file
        # that stopped being written on 21 August and reported success every turn since,
        # and the founder finds out when a session dies and there is nothing to restore.
        # LAW 6: the loop closes at the reader, so the failure goes where a reader is.
        # ESTATE_BOARD.jsonl is handed to every session at startup; a log file is not.
        _board_failure(exc)
    return 0


def _board_failure(exc: BaseException) -> None:
    """Say it where somebody is standing. Never raises: this is the failure path already."""
    try:
        line = json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "from": "session-recorder.py",
            "kind": "guard-broken",
            "text": ("the recovery file is NOT being written -- "
                     f"{type(exc).__name__}: {exc}. Sessions that die from here lose "
                     "their context. Fix before trusting --restore."),
        }, ensure_ascii=False)
        board = Path.home() / ".claude" / "ESTATE_BOARD.jsonl"
        with open(board, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def cmd_restore(cwd: str) -> int:
    f = PROJECTS / _slug(cwd) / "checkpoints" / "RECOVERY-LATEST.md"
    if not f.exists():
        print(f"no recovery file for {cwd}", file=sys.stderr)
        return 2
    print(f.read_text())
    return 0


def cmd_list() -> int:
    rows = sorted(PROJECTS.glob("*/checkpoints/RECOVERY-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not rows:
        print("nothing recorded yet")
        return 0
    for p in rows[:40]:
        if p.name == "RECOVERY-LATEST.md":
            continue
        print(f"{time.strftime('%m-%d %H:%M', time.localtime(p.stat().st_mtime))}  {p}")
    return 0


def selftest() -> int:
    import tempfile
    global PROJECTS
    fails = []

    def check(n, c, d=""):
        print(f"  {'PASS' if c else 'FAIL'}  {n}{'  ' + d if d else ''}")
        if not c:
            fails.append(n)

    with tempfile.TemporaryDirectory() as td:
        PROJECTS = Path(td) / "projects"
        tr = Path(td) / "t.jsonl"
        rows = [
            {"type": "user", "message": {"content": "first ask, verbatim"}},
            {"type": "user", "message": {"content": "<system-reminder>noise</system-reminder>"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/x/a.py"}},
                {"type": "tool_use", "name": "Bash", "input": {"command": "cat > /x/b.md <<'E'\nhi\nE"}},
                {"type": "text", "text": "I did the thing."}]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "second ask"}]}},
            {"type": "queue-operation", "operation": "enqueue", "prompt": "typed mid-turn"},
        ]
        tr.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        p = record(tr, "abcdef1234", td)
        body = p.read_text()

        check("founder turns kept verbatim and in order",
              body.index("first ask, verbatim") < body.index("second ask"))
        check("system noise dropped", "system-reminder" not in body)
        check("Write target recorded", "/x/a.py" in body)
        check("a file created by a heredoc is recorded", "/x/b.md" in body)
        check("the last reply is carried", "I did the thing." in body)
        check("a message typed MID-TURN is captured", "typed mid-turn" in body)
        check("RECOVERY-LATEST.md written too",
              (PROJECTS / _slug(td) / "checkpoints" / "RECOVERY-LATEST.md").exists())
        check("no .tmp left behind",
              not list((PROJECTS / _slug(td) / "checkpoints").glob("*.tmp")))

        # the property that matters: it must never break a turn
        bad = Path(td) / "corrupt.jsonl"
        bad.write_text("{not json\n\x00\n")
        try:
            record(bad, "zz", td)
            ok = True
        except Exception as e:
            ok = False
            print("   ", e)
        check("a corrupt transcript does not raise", ok)

        old = sys.stdin
        sys.stdin = open(os.devnull)
        try:
            check("--hook returns 0 on garbage stdin", cmd_hook() == 0)
        finally:
            sys.stdin = old

    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        sys.exit(selftest())
    if "--restore" in a:
        sys.exit(cmd_restore(os.getcwd()))
    if "--list" in a:
        sys.exit(cmd_list())
    if "--hook" in a:
        sys.exit(cmd_hook())
    print(__doc__)
    sys.exit(0)
