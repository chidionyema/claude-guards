"""Incident, crew#26 CP-B (2026-08-27): ~/AGENTS.md was 35,331 bytes and is served on every request,
so every session paid for prose that binds nobody at the moment of reading (law history, the test ladder,
the capabilities register). The rule: the resident copy holds the headline, the table, the hard rules, the
reply format and the compact instructions, and nothing else; everything moved lives verbatim in AGENTS-FULL.md.
This is a ratchet: the ceiling only ever falls."""
from pathlib import Path

LAWS = Path(__file__).resolve().parent.parent / "laws"
CEILING = 15 * 1024          # 14,735 on 2026-08-27; lower this when the file shrinks, never raise it


def test_resident_copy_fits_and_moved_blocks_survive_verbatim():
    resident = (LAWS / "AGENTS.md").read_text()
    full = (LAWS / "AGENTS-FULL.md").read_text()
    assert len(resident.encode()) <= CEILING, len(resident.encode())
    for head in ("# THE HEADLINE", "| # | Law | Fires |", "# THE FOUR HARD RULES", "## Reply format", "# Compact instructions"):
        assert head in resident, head
    for moved in ("# LAW OF CONTINUOUS EXECUTION", "# LAW OF LAZY CONSENSUS", "# LAW OF TELEMETRY COVERAGE",
                  "# Capabilities register", "## How to test", "## Closing a mistake", "## Context discipline"):
        assert moved not in resident, moved
        assert moved in full, moved


def test_founder_blocker_reads_the_register_where_it_now_lives():
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("fb", LAWS.parent / "founder-blocker.py")
    fb = importlib.util.module_from_spec(spec); sys.modules["fb"] = spec.loader and spec.loader.exec_module(fb) or fb
    assert fb.REGISTER.endswith("AGENTS-FULL.md")
    rows = fb.register_rows(str(LAWS / "AGENTS-FULL.md"))
    assert any("vault" in need.lower() for need, _ in rows), rows[:3]
