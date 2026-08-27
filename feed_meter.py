"""feed_meter: the measured token bill, one line for every handoff (crew#26 CP-D).

Reads estate/estate_spend.py --json (the meter that reproduces ~/.claude.json costUSD to 7
figures). Founder, 2026-08-27: "so how do we solve this, super crucial." A number nobody sees
is not an instrument (LAW 28); a handoff that carries $/request makes the cut visible daily.
BLIND when the meter cannot run; never a guess. A library, not a guard: it decides nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

METER_MARK = "📍 METER:"


def meter_line(timeout: float = 90.0) -> str:
    """The 📍 METER line, or a BLIND line naming why the meter did not answer."""
    try:
        script = Path(__file__).resolve().parent / "estate" / "estate_spend.py"
        out = subprocess.run([sys.executable, str(script), "--json"], capture_output=True,
                             text=True, timeout=timeout).stdout
        d = json.loads(out)
        total, reqs = float(d["total"]), int(d["requests"])
        per = total / reqs if reqs else 0.0
        drv = d.get("by_driver") or {}
        transport = sum(float(drv.get(k, 0)) for k in ("cache_read", "cache_write", "raw_input"))
        share = (transport / total * 100) if total else 0.0
        models = ", ".join(f"{m} {v / total * 100:.0f}%" for m, v in
                           sorted((d.get("by_model") or {}).items(), key=lambda kv: -kv[1])[:3])
        return (f"{METER_MARK} {d['day']} ${total:,.2f} {reqs:,} req ${per:.3f}/req "
                f"transport {share:.0f}% | {models} (crew#26)")
    except Exception as exc:  # noqa: BLE001
        return f"{METER_MARK} BLIND: estate_spend.py did not answer ({type(exc).__name__}) (crew#26)"
