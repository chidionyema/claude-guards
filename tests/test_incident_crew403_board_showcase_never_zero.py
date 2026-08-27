"""Incident test (rung 4): crew#403: the board's science section reads the generated showcase.

Both ways in one run: no page on the machine is UNKNOWN with the generating command,
never a zero row; a page whose state carries stale sources above zero grades WARN,
and the page link row is GOOD when the page is fresh.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import founder_board as fb  # noqa: E402


def test_absent_page_is_unknown_with_the_command(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "CREW", str(tmp_path))
    rows = fb.collect_science_showcase()
    assert [r.state for r in rows] == [fb.UNKNOWN]
    assert "science/showcase.py" in rows[0].command
    assert rows[0].value == "UNKNOWN"


def test_fresh_page_with_stale_sources_is_warn(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "CREW", str(tmp_path))
    (tmp_path / "docs" / "science").mkdir(parents=True)
    (tmp_path / "science").mkdir()
    (tmp_path / "docs" / "science" / "SHOWCASE.md").write_text("# page\n")
    (tmp_path / "science" / "showcase-state.json").write_text(json.dumps(
        {"generated": "2026-08-27T00:00Z", "numbers": {"warehouse rows": 47399, "stale sources": 1, "contract violations": 0}}))
    rows = {r.label: r for r in fb.collect_science_showcase()}
    assert rows["Science showcase page"].state == fb.GOOD
    assert rows["warehouse rows"].state == fb.GOOD and rows["warehouse rows"].value == "47399"
    assert rows["stale sources"].state == fb.WARN
    assert rows["contract violations"].state == fb.GOOD
