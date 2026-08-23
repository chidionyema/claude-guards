#!/usr/bin/env python3
"""Consult backends that are one HTTPS call to a key, with no browser in them.

Why this exists. Until 2026-08-23 every backend in the cascade that could give a
strong answer was a browser bridge: a headless Chrome holding a logged-in
session to kimi.ai or chat.deepseek.com. Those work, and they fail in a way
nothing else here fails: a session expires, a login wall appears, a page layout
moves, and the rail is gone until a person signs in again. LAW 27 calls a login
a cost you pay once per identity; a bridge turns it into an operational one.

A keyed HTTPS API is the opposite shape. No session, no page, nothing to expire
while nobody is watching. Three of them are wired here, and they are three rather
than one on purpose: LAW 19 is about the exit, and an exit through a single
vendor is the thing we are trying to stop having.

    openrouter  one key reaching 422 models across Anthropic, OpenAI, Google,
                DeepSeek, Qwen and Mistral, measured 2026-08-23. The broadest
                exit there is: if a lab dies, the model string changes and
                nothing else does. Balance was $-0.17 on that date, so it is
                real and it is empty.
    groq        a free tier, so it keeps working when there is no money at all.
                Its models are reasoning models and they spend the token budget
                thinking, which returns an empty answer under a tight cap and
                reads exactly like a dead rail.
    mistral     a second paid rail with credit on it, and codestral for code.

They go FIRST in the cascade, ahead of the bridges. Not because the answers are
better, which is unmeasured, but because they are the only strong rails that
cannot be taken away by a session expiring while nobody is watching.

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

#: The same two files rotate-key.py already treats as the estate's key stores.
#: A launchd job gets no interactive shell, so an export in ~/.zshrc is
#: invisible to it and reading these is the only way a daemon sees a key.
STORES = [HOME / ".config/llm/secrets.sh", HOME / ".config/wave/secrets.sh"]

#: 2000, not the model default. Without a cap OpenRouter reserves the model's
#: whole context up front and refuses with a 402 the moment the balance cannot
#: cover a 16k reservation, even when the answer is one word. And 2000 rather
#: than something small because groq's models are reasoning models: they spend
#: the budget thinking and return empty content under a tight cap, which is
#: indistinguishable from a dead rail. Both failures were measured 2026-08-23.
MAX_TOKENS = int(os.environ.get("CONSULT_MAX_TOKENS", "2000"))


def _key(var):
    """The key from the environment, else from the 0600 stores. Never logged."""
    k = os.environ.get(var)
    if k:
        return k.strip()
    pat = re.compile(r'\s*(?:export\s+)?' + re.escape(var) + r'\s*=\s*"?([^"\s#]+)"?')
    for s in STORES:
        try:
            for line in s.read_text().splitlines():
                m = pat.match(line)
                if m:
                    return m.group(1)
        except OSError:
            continue
    return ""


class DirectAPIBackend:
    """One OpenAI-shaped chat endpoint behind one key.

    Every rail here speaks the same wire format, so the differences are three
    strings and nothing else. That is the point: adding a fourth provider is a
    line in DIRECT below, not a new file, and swapping one out when it dies is
    the same line.
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
            return False, (f"no {self.keyvar} in the environment or in "
                           + " or ".join(str(s) for s in STORES))
        return True, f"{self.model()} via {self.name} ({self.note})"

    def ask(self, prompt, timeout):
        key = _key(self.keyvar)
        if not key:
            raise RuntimeError(f"no {self.keyvar}")
        body = json.dumps({"model": self.model(), "max_tokens": MAX_TOKENS,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {key}",
                   #: urllib announces itself as Python-urllib and groq answers
                   #: that with a bare 403 Forbidden, no body, while the same
                   #: request from curl succeeds. Measured 2026-08-23. Without
                   #: this line the rail reads as a dead key rather than a
                   #: blocked client, which is the wrong thing to go debug.
                   "User-Agent": "estate-consult/1.0"}
        headers.update(self.extra)
        req = urllib.request.Request(self.url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            #: Read the body. These APIs put the real reason there and the status
            #: alone says only that something was wrong. Truncated so a provider
            #: echoing the request can never paste a key into a log.
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
                raise RuntimeError(f"{self.name} spent its whole {MAX_TOKENS}-token "
                                   "budget reasoning and never wrote an answer")
            raise RuntimeError(f"{self.name} returned an empty response")
        return out


#: The three rails, in the order the cascade should try them. groq first because
#: it is the only one that still answers when the company has no money, which is
#: the state this estate has actually been in. openrouter last of the three
#: because it is the broadest and the emptiest.
DIRECT = [
    DirectAPIBackend("groq", "https://api.groq.com/openai/v1/chat/completions",
                     "openai/gpt-oss-120b", "GROQ_API_KEY",
                     "free tier, works with no money in the account"),
    DirectAPIBackend("mistral", "https://api.mistral.ai/v1/chat/completions",
                     "mistral-medium-2508", "MISTRAL_API_KEY",
                     "paid, has credit, codestral for code"),
    DirectAPIBackend("openrouter", "https://openrouter.ai/api/v1/chat/completions",
                     "deepseek/deepseek-chat", "OPENROUTER_API_KEY",
                     "422 models behind one key; top it up and every lab is reachable",
                     #: Not credentials. OpenRouter attributes traffic by these
                     #: and they keep the account's usage legible.
                     {"HTTP-Referer": "https://github.com/chidionyema",
                      "X-Title": "estate-consult"}),
]
