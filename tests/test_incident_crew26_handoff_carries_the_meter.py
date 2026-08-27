"""Incident test, crew#26 CP-D (2026-08-27): the token bill was $1,375 by midday and no handoff
carried it. Rule: every appended handoff carries a measured 📍 METER: line, or BLIND, never a guess."""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]


def _fg():
    spec = importlib.util.spec_from_file_location("feed_guard", HERE / "feed-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BODY = "🟡 Active: x\n🔧 TOUCHES: none\n🔀 OVERLAP: none\n"


def test_incident_crew26_every_handoff_carries_the_meter(tmp_path, monkeypatch):
    fg = _fg()
    monkeypatch.setattr(fg, "holders", lambda *a, **k: [])
    feed = tmp_path / "feed.md"
    assert fg.append(feed, "s1", "lane", BODY, meter="📍 METER: 2026-08-27 $1.00 1 req $1.000/req") is None
    text = feed.read_text()
    assert "📍 METER: 2026-08-27 $1.00" in text


def test_incident_crew26_a_meter_the_author_wrote_is_not_doubled(tmp_path, monkeypatch):
    fg = _fg()
    monkeypatch.setattr(fg, "holders", lambda *a, **k: [])
    feed = tmp_path / "feed.md"
    assert fg.append(feed, "s1", "lane", BODY + "📍 METER: mine\n", meter="📍 METER: theirs") is None
    assert feed.read_text().count("📍 METER:") == 1


def test_incident_crew26_meter_is_blind_not_a_guess_when_the_script_is_missing(monkeypatch):
    fg = _fg()
    monkeypatch.setattr(fg, "Path", type("P", (), {}))  # any exception path -> BLIND
    line = fg.meter_line(timeout=1)
    assert line.startswith("📍 METER: BLIND")
