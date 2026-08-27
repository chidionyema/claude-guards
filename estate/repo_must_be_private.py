#!/usr/bin/env python3
"""crew#227 / LAW 45: a repository that holds ciphertext is proved private every hour, from off the Mac.

Incident, 2026-08-27: chidionyema/estate-secrets (41 sops-encrypted files under secrets/dev) was
PUBLIC. Its own pre-push hook refused "visibility is 'PUBLIC', not PRIVATE - refusing to push
ciphertext", which is how it was noticed, but a hook fires only when someone pushes from this
laptop. in-git.py knows `private: true` and was never scheduled. Nothing off the Mac looked.

Mature tool rejected: GitHub's "restrict repository visibility changes" policy exists only for
organisations; this is a personal account, so there is no setting to buy. The probe needs no
credential: an unauthenticated GET of /repos/<owner>/<name> returns 200 only when the repo is
public, 404 when it is private. Anything a stranger can read, this reads; anything they cannot,
it cannot either. That is the property being enforced, so it is the probe.

Exit 0: every listed repo is hidden from the anonymous internet. Exit 1: at least one is public,
named on stderr. Exit 2: the probe itself could not reach GitHub (BLIND, never a verdict).
"""
import json
import sys
import urllib.error
import urllib.request

MUST_BE_PRIVATE = ("chidionyema/estate-secrets",)


def anonymous_status(repo, opener=None):
    """HTTP status a stranger gets for the repo: 200 public, 404 private/absent, None unreachable."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "claude-guards repo_must_be_private"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def verdicts(repos=MUST_BE_PRIVATE, opener=None):
    """One (repo, status, verdict) per repo; verdict in {'private', 'PUBLIC', 'BLIND'}."""
    out = []
    for repo in repos:
        st = anonymous_status(repo, opener)
        v = "BLIND" if st is None else ("private" if st == 404 else "PUBLIC")
        out.append((repo, st, v))
    return out


def main(argv=None):
    rows = verdicts()
    rc = 0
    for repo, st, v in rows:
        print(json.dumps({"repo": repo, "anonymous_http": st, "verdict": v}))
        if v == "PUBLIC":
            print(f"::error::{repo} is readable by anyone (HTTP {st}); it holds ciphertext. "
                  f"Fix: gh repo edit {repo} --visibility private --accept-visibility-change-consequences",
                  file=sys.stderr)
            rc = 1
        elif v == "BLIND" and rc == 0:
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
