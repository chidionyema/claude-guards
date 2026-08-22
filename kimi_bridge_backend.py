#!/usr/bin/env python3
"""consultd.py backend that talks to the Kimi browser bridge over loopback.

Stdlib only, on purpose. consultd.py runs under Apple's signed
/usr/bin/python3; the bridge runs under its own virtualenv with Playwright in
it. They share nothing but an HTTP port, so a broken Playwright install cannot
stop the daemon from starting and falling through to ollama.

The contract is the one in consultd.py, not the one in the README that came
with the pasted draft:

    ready()             -> (bool, detail)      consultd.py:316 does r[name][0]
    ask(prompt, timeout) -> str
    name, cap           class attributes

The draft returned a bare bool from ready(), which raised
`TypeError: 'bool' object is not subscriptable` inside Service.live() and took
the ollama fallback down with it, because readiness() maps the whole chain
before any backend is tried.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BRIDGE_URL = os.environ.get("KIMI_BRIDGE_URL_LOCAL", "http://127.0.0.1:8766")


class KimiBridgeBackend:
    name = "kimi-bridge"
    free = True
    # Its slice of one consult's wall clock. The bridge drives a real browser,
    # so it is slower than an API and must still leave ollama room to answer
    # inside the same budget.
    cap = 300  # kimi is a reasoning model; 5 min is normal thinking, not a fault

    def __init__(self, url: str = BRIDGE_URL):
        self.url = url.rstrip("/")

    def _get(self, path, timeout):
        req = urllib.request.Request(f"{self.url}{path}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def ready(self):
        """A pair, because that is what the cascade unpacks."""
        try:
            h = self._get("/health", 5)
        except urllib.error.URLError as e:
            return False, f"bridge daemon is not on {self.url} ({e.reason})"
        except Exception as e:
            return False, f"bridge health failed: {type(e).__name__}: {e}"
        if h.get("status") == "healthy":
            return True, h.get("detail") or "signed in"
        # Not an error. A signed-out bridge is a normal state with a known fix,
        # and saying so beats a stack trace the founder has to decode.
        return False, h.get("detail") or h.get("status", "unhealthy")

    def ask(self, prompt, timeout):
        body = json.dumps({"prompt": prompt, "timeout": int(timeout)}).encode()
        req = urllib.request.Request(
            f"{self.url}/query", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 30) as r:
                out = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read().decode())
            except Exception:
                raise RuntimeError(f"bridge returned HTTP {e.code}")
        if out.get("success") and out.get("answer"):
            return out["answer"]
        raise RuntimeError(out.get("error") or "bridge returned no answer")
