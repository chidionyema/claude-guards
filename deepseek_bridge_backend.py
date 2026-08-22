#!/usr/bin/env python3
"""consultd.py backend for the DeepSeek browser bridge.

Same mechanism as the Kimi bridge and, deliberately, the same engine: it is a
second instance of kimi_bridge.py pointed at chat.deepseek.com (launchd job
ai.estate.deepseek-bridge, loopback 127.0.0.1:8767). The founder signs in once
by hand; the profile at ~/.deepseek-bridge/profile keeps the session and
launchd owns it after that (LAW 27). This class only differs from the Kimi one
in its name, its port and its time cap, so it subclasses rather than copies.
"""

from __future__ import annotations

import os

from kimi_bridge_backend import KimiBridgeBackend

BRIDGE_URL = os.environ.get("DEEPSEEK_BRIDGE_URL_LOCAL", "http://127.0.0.1:8767")


class DeepSeekBridgeBackend(KimiBridgeBackend):
    name = "deepseek"
    free = True
    # The mid-cascade fallback: quicker to give up than the patient kimi bridge,
    # so it leaves ollama room inside the same consult budget.
    cap = 150

    def __init__(self, url: str = BRIDGE_URL):
        super().__init__(url)
