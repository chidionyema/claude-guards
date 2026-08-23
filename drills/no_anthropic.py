#!/usr/bin/env python3
"""Prove this estate can still do work with Anthropic switched off.

LAW 19: a dependency whose exit has never been drilled is not portable, it is a
hope. Everything here runs through one vendor, and until 2026-08-23 nobody had
ever once checked whether the alternatives on this machine actually work. The
laws were already symlinked into ~/.codex, ~/.gemini and ~/.cursor, which is the
groundwork for an exit nobody had taken.

The drill runs in a throwaway directory with every Anthropic credential stripped
from the environment, so a rail that quietly falls back to Claude fails rather
than passes. Two layers, because they fail for different reasons and only one of
them is the existential one:

  SUBSTRATE  can we get an answer out of a model at all. A key and a POST.
  AGENT      can something read a file, change it, and prove it changed. This is
             the layer the founder's working pattern actually sits on. A chat
             completion is not a replacement for an agent that edits code.

An agent rail passes only when the file on disk is different afterwards in the
exact way that was asked. Not when the process exits 0, and not when the model
says it did it: on 2026-08-23 both alternate CLIs exited having done nothing and
printed a cheerful paragraph about it.

    no_anthropic.py            run both layers, print the table
    no_anthropic.py --json     the same as one record
    no_anthropic.py --quick    substrate only, no agent (seconds, not minutes)

Exit 0 when at least one substrate rail AND at least one agent rail pass. Exit 1
otherwise, which is the honest state of "we cannot work today without them".
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

#: Stripped from the child environment. A rail that passes only because it
#: reached for one of these has proved nothing, and that is not hypothetical:
#: aider reads ANTHROPIC_API_KEY on its own and will happily use it.
ANTHROPIC_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                  "CLAUDE_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

#: name, url, model, key env var, wire format. Ordered by what we would actually
#: reach for: openrouter first because one key there reaches 422 models across
#: every major lab, which is the whole point of the exercise. ollama last and
#: always, because it is the only one that survives having no account anywhere.
SUBSTRATE = [
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions",
     "deepseek/deepseek-chat", "OPENROUTER_API_KEY", "oai"),
    ("groq", "https://api.groq.com/openai/v1/chat/completions",
     "openai/gpt-oss-120b", "GROQ_API_KEY", "oai"),
    ("mistral", "https://api.mistral.ai/v1/chat/completions",
     "mistral-small-latest", "MISTRAL_API_KEY", "oai"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
     "gemini-2.5-flash", "GEMINI_API_KEY", "gemini"),
    ("deepseek", "https://api.deepseek.com/chat/completions",
     "deepseek-chat", "DEEPSEEK_API_KEY", "oai"),
    ("ollama", "http://127.0.0.1:11434/v1/chat/completions",
     "llama3.2:latest", None, "oai"),
]

WORD = "PORTABLE"
#: "Reply with exactly one word and nothing else: PORTABLE" reads as a riddle to
#: a 3B local model, which answered "Device", "Charger" and "Storage" on three
#: consecutive runs. It was following an instruction it had understood as
#: word-association. Copying is the smallest thing a model can be asked to do,
#: and it is the thing this drill actually needs to know a rail can do.
ASK = f"Copy the following word exactly, and write nothing else. {WORD}"


def _key_from_store(var):
    """A key out of the estate's 0600 stores. Never printed, only passed on.

    The drill runs from launchd on a schedule, and a launchd job gets no
    interactive shell, so every export in ~/.zshrc is invisible to it. Without
    this the scheduled run would report every paid rail dead and the one place
    the drill matters most is the place it would lie.
    """
    import re
    pat = re.compile(r'\s*(?:export\s+)?' + re.escape(var) + r'\s*=\s*"?([^"\s#]+)"?')
    for s in (os.path.expanduser("~/.config/llm/secrets.sh"),
              os.path.expanduser("~/.config/wave/secrets.sh")):
        try:
            with open(s) as fh:
                for line in fh:
                    m = pat.match(line)
                    if m:
                        return m.group(1)
        except OSError:
            continue
    return ""


def clean_env():
    e = dict(os.environ)
    for v in ANTHROPIC_VARS:
        e.pop(v, None)
    return e


def post(url, headers, body, timeout):
    """POST through curl --config so no credential ever reaches argv.

    ps(1) shows every argument of every process on this machine to every other
    process on it, so a bearer token passed as -H is a token in a log somebody
    can read. LAW 21 says a secret never lands anywhere it can be read again,
    and argv is exactly such a place.
    """
    cfg = [f'url = "{url}"', 'request = "POST"']
    for h in headers:
        cfg.append(f'header = {json.dumps(h)}')
    cfg.append(f"data = {json.dumps(json.dumps(body))}")
    p = subprocess.run(["curl", "-s", "-m", str(timeout), "--config", "-"],
                       input="\n".join(cfg), capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"error": {"message": (p.stdout or p.stderr or "no response")[:120]}}


def substrate_one(name, url, model, keyvar, wire, timeout=150):
    key = (os.environ.get(keyvar) or _key_from_store(keyvar)) if keyvar else "local"
    if not key:
        return {"rail": name, "layer": "substrate", "ok": False, "why": f"{keyvar} is not set"}
    t0 = time.time()
    if wire == "gemini":
        d = post(f"{url}?key={key}", ["Content-Type: application/json"],
                 {"contents": [{"parts": [{"text": ASK}]}]}, timeout)
    else:
        hdrs = ["Content-Type: application/json"]
        if keyvar:
            hdrs.append(f"Authorization: Bearer {key}")
        d = post(url, hdrs, #: 400, not 32. A reasoning model spends its budget thinking and
                             #: returns empty content if the cap is tight, which reads
                             #: exactly like a dead rail. groq failed this way first.
                             {"model": model, "max_tokens": 400,
                             "messages": [{"role": "user", "content": ASK}]}, timeout)
    dt = round(time.time() - t0, 1)
    if isinstance(d, dict) and d.get("error"):
        e = d["error"]
        return {"rail": name, "layer": "substrate", "ok": False, "seconds": dt,
                "why": str(e.get("message", e) if isinstance(e, dict) else e)[:110]}
    try:
        if "candidates" in d:
            txt = d["candidates"][0]["content"]["parts"][0]["text"]
        else:
            txt = d["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        return {"rail": name, "layer": "substrate", "ok": False, "seconds": dt,
                "why": "answered, but not in a shape we can read: " + json.dumps(d)[:80]}
    ok = WORD.lower() in (txt or "").lower()
    return {"rail": name, "layer": "substrate", "ok": ok, "seconds": dt,
            "why": (txt or "").strip()[:60] if ok else f"said {(txt or 'nothing')[:40]!r}, wanted {WORD}"}


#: The agent task. Deliberately dull and mechanically checkable: change one
#: known line in one known file. A task with any judgement in it turns the drill
#: into an opinion about model quality, and this drill is about whether the rail
#: exists at all.
SEED = "version = 1\nname = estate\n"
WANT = "version = 2"
TASK = ("In the file config.toml in this directory, change the line 'version = 1' "
        "to 'version = 2'. Change nothing else. Do not ask any questions.")


def agent_one(name, argv, env_extra=None, timeout=240):
    """Run one agent CLI on the task and check the FILE, not the exit code."""
    if not shutil.which(argv[0]) and not os.path.exists(argv[0]):
        return {"rail": name, "layer": "agent", "ok": False, "why": "not installed"}
    d = tempfile.mkdtemp(prefix=f"drill-{name}-")
    try:
        cfg = os.path.join(d, "config.toml")
        with open(cfg, "w") as fh:
            fh.write(SEED)
        env = clean_env()
        env.update(env_extra or {})
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=d, env=env, capture_output=True,
                               text=True, timeout=timeout)
            tail = ((p.stdout or "") + (p.stderr or "")).strip().replace("\n", " ")[-110:]
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc, tail = 124, f"still running after {timeout}s"
        dt = round(time.time() - t0, 1)
        after = open(cfg).read()
        ok = WANT in after
        #: The file is the verdict. An agent that exits 0 and changed nothing is
        #: the exact failure this line exists to catch, and both CLIs on this
        #: machine did precisely that the first time they were asked.
        why = "config.toml now says version = 2" if ok else \
              (f"file unchanged (rc={rc}) {tail}" if rc == 0 else f"rc={rc} {tail}")
        return {"rail": name, "layer": "agent", "ok": ok, "seconds": dt, "why": why[:150]}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def agents():
    """Every alternate agent rail worth trying, in the order we would reach for one.

    aider first, and three times, because it is the only one here that is
    provider agnostic by design: the same binary drives any of these by changing
    one string. mistral leads because on 2026-08-23 it was the rail with credit
    on it and codestral is a coding model; it did the task for $0.00024. groq is
    second because it is free and therefore the rail that survives having no
    money at all. openrouter is third and was at $-0.17 on that date, which is
    why it is not first despite reaching every lab.

    The vendor CLIs come last. Both are installed, both refused on 2026-08-23,
    and neither refused for a reason that is about us: cursor-agent wants a spend
    limit set on the account, gemini-cli wants the folder marked trusted before
    it will edit anything unattended. Those are one-time settings, not
    architecture, and they are exactly the kind of thing that is discovered
    during an outage unless a drill finds it first.
    """
    out = []
    for prov, model, keyvar in (("mistral", "mistral/codestral-latest", "MISTRAL_API_KEY"),
                                ("groq", "groq/openai/gpt-oss-120b", "GROQ_API_KEY"),
                                ("openrouter", "openrouter/deepseek/deepseek-chat",
                                 "OPENROUTER_API_KEY")):
        key = os.environ.get(keyvar) or _key_from_store(keyvar)
        if not key:
            continue
        out.append((f"aider-{prov}",
                    ["aider", "--model", model, "--yes-always", "--no-auto-commits",
                     "--no-git", "--no-check-update", "--no-analytics",
                     "--message", TASK, "config.toml"],
                    {keyvar: key}))
    out.append(("cursor-agent", ["cursor-agent", "-p", "-f", TASK], None))
    #: --skip-trust, and GEMINI_DEFAULT_AUTH_TYPE pushed onto the free OAuth
    #: tier. The API key route is dead: Google says its prepayment credits are
    #: depleted and the CLI answers 429. The first version of this drill passed
    #: GEMINI_CLI_TRUSTED_FOLDER, which is not the name of anything, so it
    #: reported a trust refusal as if it were the whole story.
    out.append(("gemini-cli", ["gemini", "-y", "--skip-trust", "-p", TASK],
                {"GEMINI_DEFAULT_AUTH_TYPE": "oauth-personal", "GEMINI_API_KEY": ""}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quick", action="store_true", help="substrate only")
    a = ap.parse_args()

    rows = [substrate_one(*s) for s in SUBSTRATE]
    if not a.quick:
        #: Stop at the first agent rail that works. The question is whether an
        #: exit exists, not which exit is best, and carrying on to try two more
        #: known-misconfigured CLIs turns a 40 second drill into a 4 minute one.
        #: A drill that is slow is a drill that gets scheduled weekly, and this
        #: is the one thing that should not go a week unchecked.
        for g in agents():
            r = agent_one(*g)
            rows.append(r)
            if r["ok"]:
                break

    sub = [r for r in rows if r["layer"] == "substrate"]
    agt = [r for r in rows if r["layer"] == "agent"]
    sub_ok = [r for r in sub if r["ok"]]
    agt_ok = [r for r in agt if r["ok"]]
    passed = bool(sub_ok) and (a.quick or bool(agt_ok))

    rec = {"iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "substrate_ok": [r["rail"] for r in sub_ok],
           "agent_ok": [r["rail"] for r in agt_ok],
           "passed": passed, "rows": rows}

    if a.json:
        print(json.dumps(rec, indent=2))
        return 0 if passed else 1

    for layer, group in (("SUBSTRATE  a model answers at all", sub),
                         ("AGENT      something edits a file and proves it", agt)):
        if not group:
            continue
        print(f"\n{layer}")
        for r in group:
            print(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['rail']:<18} "
                  f"{str(r.get('seconds', '')):>6}s  {r['why']}")
    print(f"\n{len(sub_ok)}/{len(sub)} substrate rails and {len(agt_ok)}/{len(agt)} agent rails "
          f"work with Anthropic switched off.")
    print("VERDICT: " + ("the estate can still work without Anthropic." if passed
                         else "the estate CANNOT work without Anthropic today."))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
