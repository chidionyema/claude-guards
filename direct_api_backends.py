#!/usr/bin/env python3
"""Consult backends that are one HTTPS call to a key, with no browser in them.

Why this exists. Until 2026-08-23 every backend in the cascade that could give a
strong answer was a browser bridge: a headless Chrome holding a logged-in
session to kimi.ai or chat.deepseek.com. Those work, and they fail in a way
nothing else here fails: a session expires, a login wall appears, a page layout
moves, and the rail is gone until a person signs in again. LAW 27 calls a login
a cost you pay once per identity; a bridge turns it into an operational one.

A keyed HTTPS API is the opposite shape. No session, no page, nothing to expire
while nobody is watching. As of 2026-08-29 (crew#568 Phase 2) there is ONE
endpoint here: the estate's LiteLLM router, and the cascade is its lanes as a
fallback. The router is the only outbound consultd is allowed to speak to, so
the differences between rows in DIRECT below are the lane name and a human
note -- the URL and the key are the router's, and the lane name is the model
the router hands off to.

THE KEY never reaches argv. urllib puts it in a header; a subprocess would put
it in a command line, and ps(1) shows every argument of every process on this
machine to every other process on it (LAW 21).

THE DEFAULT MODEL is deliberately not a Claude one. A fallback that reaches for
Anthropic when Anthropic is the thing that failed is not a fallback, and that is
the exact mistake this file exists to avoid.
"""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()

#: The same two files rotate-key.py already treats as the estate's key stores,
#: plus the prospector secrets drop for LITELLM_API_KEY (a raw key in a file
#: named after the var, read whole by the basename branch in _key below). A
#: launchd job gets no interactive shell, so an export in ~/.zshrc is invisible
#: to it and reading these is the only way a daemon sees a key.
STORES = [
    HOME / ".config/llm/secrets.sh",
    HOME / ".config/wave/secrets.sh",
    HOME / ".config/prospector/secrets.d" / "LITELLM_API_KEY",
]

#: 2000, not the model default. Without a cap a lane's upstream reserves the
#: model's whole context up front and refuses with a 402 the moment the balance
#: cannot cover a 16k reservation, even when the answer is one word. And 2000
#: rather than something small because reasoning lanes spend the budget thinking
#: and return empty content under a tight cap, which is indistinguishable from
#: a dead rail. Both failures were measured 2026-08-23.
MAX_TOKENS = int(os.environ.get("CONSULT_MAX_TOKENS", "2000"))


def _key(var):
    """The key from the environment, else from the 0600 stores. Never logged."""
    k = os.environ.get(var)
    if k:
        return k.strip()
    pat = re.compile(r"\s*(?:export\s+)?" + re.escape(var) + r'\s*=\s*"?([^"\s#]+)"?')
    for s in STORES:
        try:
            text = s.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            m = pat.match(line)
            if m:
                return m.group(1)
        #: A file with no NAME= line: if the store path's basename equals the
        #: var being looked up, the whole content is the key. This is how
        #: ~/.config/prospector/secrets.d/LITELLM_API_KEY is shaped.
        if s.name == var:
            stripped = text.strip()
            if stripped:
                return stripped
    return ""


class DirectAPIBackend:
    """One OpenAI-shaped chat endpoint behind one key.

    Every rail here speaks the same wire format, so the differences are three
    strings and nothing else. That is the point: adding another lane is a line
    in DIRECT below, not a new file, and reordering the cascade is the same
    line.
    """

    free = False
    #: Same cap as every other backend. A rail that hangs must not spend the
    #: whole consult budget before the next one is tried.
    cap = 150

    def __init__(self, name, url, model, keyvar, note, extra_headers=None):
        self.name = name
        self.url = url
        self._model = model
        self.keyvar = keyvar
        self.note = note
        self.extra = extra_headers or {}

    def model(self):
        return os.environ.get(f"CONSULT_{self.name.upper()}_MODEL", self._model)

    def ready(self):
        if not _key(self.keyvar):
            return False, (
                f"no {self.keyvar} in the environment or in "
                + " or ".join(str(s) for s in STORES)
            )
        return True, f"{self.model()} via {self.name} ({self.note})"

    def ask(self, prompt, timeout):
        key = _key(self.keyvar)
        if not key:
            raise RuntimeError(f"no {self.keyvar}")
        body = json.dumps(
            {
                "model": self.model(),
                "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            #: urllib announces itself as Python-urllib and a lane's
            #: upstream answers that with a bare 403 Forbidden, no body,
            #: while the same request from curl succeeds. Measured
            #: 2026-08-23. Without this line the rail reads as a dead
            #: key rather than a blocked client, which is the wrong
            #: thing to go debug.
            "User-Agent": "estate-consult/1.0",
        }
        headers.update(self.extra)
        req = urllib.request.Request(self.url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            #: Read the body. The router puts the real reason there and the
            #: status alone says only that something was wrong. Truncated so
            #: the upstream echoing the request can never paste a key into a
            #: log.
            detail = ""
            try:
                detail = json.loads(e.read()).get("error", {}).get("message", "")[:200]
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"{self.name} {e.code}: {detail or e.reason}") from None
        msg = d.get("choices", [{}])[0].get("message", {})
        out = (msg.get("content") or "").strip()
        if not out:
            #: A reasoning model that ran out of budget mid-thought leaves the
            #: thinking here and content empty. Say which happened rather than
            #: reporting an empty response and letting the next agent guess.
            if msg.get("reasoning"):
                raise RuntimeError(
                    f"{self.name} spent its whole {MAX_TOKENS}-token "
                    "budget reasoning and never wrote an answer"
                )
            raise RuntimeError(f"{self.name} returned an empty response")
        return out


#: The router's lanes, in the order the cascade should try them. They go FIRST
#: in the cascade, ahead of ollama, because they are the only strong rails and
#: because the router is the only outbound consultd is allowed to speak to
#: (crew#568 Phase 2). The URL and keyvar are the same on every row; only the
#: lane name and the human note differ, and the lane name is the model the
#: router hands off to.
LITELLM_URL = (
    os.environ.get("LITELLM_BASE_URL", "https://llm.mumchimp.com/v1")
    + "/chat/completions"
)
DIRECT = [
    DirectAPIBackend(
        "minimax",
        LITELLM_URL,
        "minimax",
        "LITELLM_API_KEY",
        "estate router lane minimax",
    ),
    DirectAPIBackend(
        "deepseek",
        LITELLM_URL,
        "deepseek",
        "LITELLM_API_KEY",
        "estate router lane deepseek",
    ),
    DirectAPIBackend(
        "groq", LITELLM_URL, "groq", "LITELLM_API_KEY", "estate router lane groq"
    ),
    DirectAPIBackend(
        "openrouter",
        LITELLM_URL,
        "openrouter",
        "LITELLM_API_KEY",
        "estate router lane openrouter",
    ),
]
