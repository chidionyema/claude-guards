#!/usr/bin/env python3
"""Refuse to let a credential reach a git remote, and find the ones already there.

secret-scrub.py already keeps keys out of the local logs that collect them by
accident: history.jsonl, .zsh_history, checkpoint notes. It runs on Stop and it
only ever looks at those files. Nothing looked at a repository.

So on 2026-08-23, asked to make two repositories public, the scan was written by
hand in a scratchpad, run once, and thrown away. The founder's reply was the
whole point: "why isnt this automated already, thats why we are always
firefighting". A check that exists only when somebody remembers to write it is
not a check, and the moment it is needed most is the moment nobody has time.

Two entry points, because the risk has two shapes.

    --diff     what THIS push adds. Fast, runs in pre-push, refuses the push.
    --history  what the repository has EVER held. Slower, runs on a schedule
               over the public repositories, because a key in an old commit is
               readable no matter what the tip says.

WHAT BLOCKS AND WHAT ONLY REPORTS, which is the difference between a gate people
keep and a gate people bypass with --no-verify. Every pattern under STRONG is
anchored on a provider's own prefix and its real length, so a match is a key or
it is a test fixture, and there is no third option. The one pattern that reads
`secret = <something long>` lives under WEAK and never blocks: on its first real
run it produced three hits in survival-stack and all three were false, an env
var name, an RFC 6238 test vector and Telegram's own documentation token. A gate
that cries wolf three times out of three gets turned off within a week.

    repo_secrets.py --repo . --diff <sha>..<sha>   exit 1 if a push carries one
    repo_secrets.py --repo . --history             exit 1 if any commit ever did
    repo_secrets.py --selftest                     prove the patterns both ways

It never prints a secret. It prints the kind, the file and the line.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

#: Anchored on a vendor prefix and a real length. A match here is a live
#: credential or a fixture, so this set is allowed to refuse a push.
STRONG = [
    ("stripe-live",     re.compile(r"sk_live_[A-Za-z0-9]{20,}")),
    ("stripe-restrict", re.compile(r"rk_live_[A-Za-z0-9]{20,}")),
    ("aws-access-key",  re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github-pat",      re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack-token",     re.compile(r"xox[baprs]-[A-Za-z0-9]{10,}-[A-Za-z0-9-]{10,}")),
    ("private-key",     re.compile(r"BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    ("anthropic-key",   re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9_-]{40,}")),
    ("openai-key",      re.compile(r"sk-proj-[A-Za-z0-9_-]{40,}")),
    ("google-api-key",  re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("fly-token",       re.compile(r"Fly[Vv]1 [A-Za-z0-9+/=]{40,}")),
    ("age-secret-key",  re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]{50,}")),
    ("npm-token",       re.compile(r"npm_[A-Za-z0-9]{36}")),
]

#: Shaped like a credential and usually is not. Reported, never blocking.
WEAK = [
    ("assigned-value", re.compile(
        r"(?i)\b(?:secret|token|password|passwd|api[_-]?key|client[_-]?secret)"
        r"\s*[:=]\s*[\"'][A-Za-z0-9/+_.-]{28,}[\"']")),
    ("jwt",            re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")),
]

#: Files whose job is to describe credentials, or to test the describing. The
#: scrubber learned the same lesson: one that eats the real secret store, or a
#: vendored test corpus, gets turned off, and a gate that is off protects nothing.
EXEMPT = re.compile(
    r"(__pycache__|\.pyc$|/node_modules/|\.lock$|/vendor/|"
    r"secret-scrub|repo_secrets|secret-surface|"
    r"hermes-agent/tests?/|/fixtures?/|\.example$|\.sample$)")


def git(repo, *args, binary_ok=True):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                       text=True, errors="replace")
    return p.stdout


def _hits(text, path, blocking_only=False):
    out = []
    sets = STRONG if blocking_only else STRONG + WEAK
    for kind, rx in sets:
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            out.append({"kind": kind, "path": path, "line": line,
                        "blocking": any(kind == k for k, _ in STRONG)})
    return out


def scan_diff(repo, rev_range):
    """Only the lines this push ADDS. What was already there is the sweep's job."""
    diff = git(repo, "diff", "--unified=0", "--no-color", rev_range)
    hits, path = [], "?"
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path = raw[6:]
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        if EXEMPT.search(path):
            continue
        for h in _hits(raw[1:], path):
            hits.append(h)
    return hits


def scan_history(repo):
    """Every added line in every commit, because a deleted key is still public."""
    log = git(repo, "log", "--all", "-p", "--unified=0", "--no-color")
    hits, path = [], "?"
    for raw in log.splitlines():
        if raw.startswith("+++ b/"):
            path = raw[6:]
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        if EXEMPT.search(path):
            continue
        hits.extend(_hits(raw[1:], path))
    return hits


def scan_tree(repo):
    hits = []
    for f in git(repo, "ls-files").splitlines():
        if EXEMPT.search(f):
            continue
        hits.extend(_hits(git(repo, "show", "HEAD:" + f), f))
    return hits


def report(hits, where):
    strong = [h for h in hits if h["blocking"]]
    weak = [h for h in hits if not h["blocking"]]
    print(f"{where}: {len(strong)} blocking, {len(weak)} to verify by hand")
    for h in strong:
        print(f"  REFUSE  {h['kind']:<18} {h['path']}:{h['line']}")
    for h in weak[:20]:
        print(f"  check   {h['kind']:<18} {h['path']}:{h['line']}")
    return 1 if strong else 0


def selftest():
    """Both directions. A gate that only proves it fires has proved nothing."""
    must_fire = [
        "AKIA" + "A" * 16,
        "ghp_" + "a" * 36,
        "-----BEGIN RSA PRIVATE KEY-----",
        "sk-ant-api03-" + "x" * 45,
        "AGE-SECRET-KEY-1" + "A" * 55,
    ]
    must_not = [
        'if (process.env.CF_API_TOKEN) return process.env.CF_API_TOKEN',
        "secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=Survival",
        "const BOT = '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'",
        "sk-ant-api03-SHORT",
    ]
    ok = True
    for s in must_fire:
        got = [h for h in _hits(s, "t.txt") if h["blocking"]]
        if not got:
            print(f"  MISSED  {s[:24]}...")
            ok = False
    for s in must_not:
        got = [h for h in _hits(s, "t.txt") if h["blocking"]]
        if got:
            print(f"  FALSE   {got[0]['kind']} on {s[:40]}")
            ok = False
    print("repo_secrets selftest", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--diff", metavar="RANGE")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--tree", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.diff:
        return report(scan_diff(a.repo, a.diff), f"{a.repo} {a.diff}")
    if a.history:
        return report(scan_history(a.repo), f"{a.repo} full history")
    return report(scan_tree(a.repo), f"{a.repo} tree at HEAD")


if __name__ == "__main__":
    sys.exit(main())
