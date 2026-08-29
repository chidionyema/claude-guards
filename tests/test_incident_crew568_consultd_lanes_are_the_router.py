"""crew#568 Phase 2: consultd's keyed backends are lanes of the estate router, never a vendor host.

The laptop carried four vendor keys and two local bridges (kimi, deepseek) for one job the router
already does. Every DIRECT row must point at LITELLM_BASE_URL with LITELLM_API_KEY, and no bridge
backend may come back.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ROOT / "direct_api_backends.py"
CONSULTD = ROOT / "consultd.py"
DEPS = ROOT / "drills" / "dependencies.json"


def test_every_direct_row_is_a_router_lane() -> None:
    src = BACKENDS.read_text()
    assert "LITELLM_BASE_URL" in src
    for vendor in (
        "api.groq.com",
        "api.minimax",
        "api.deepseek.com",
        "openrouter.ai/api",
    ):
        assert vendor not in src, vendor
    keys = set(re.findall(r'"([A-Z_]+_API_KEY)"', src))
    assert keys == {"LITELLM_API_KEY"}, keys


def test_the_bridges_are_gone() -> None:
    src = CONSULTD.read_text()
    assert "KimiBridge" not in src and "DeepseekBridge" not in src


def test_the_router_host_and_key_are_classified() -> None:
    import json

    d = json.loads(DEPS.read_text())
    assert "llm.mumchimp.com" in d["hosts"]
    assert "LITELLM_API_KEY" in d["credentials"]
