"""Incident test, crew#629 CP4 (2026-08-29): the first handoff that carried a 📎 FACTS: line was
refused by policy/feed.rego, whose mark set had not learned the ninth line. Rule: a handoff may
carry 📎 FACTS: pointing at the ticket's generated Infra facts block (bin/idp-ticket-facts); nine
lines fit; a handoff without it is appended with a note, never refused (report-only until CP5)."""

import importlib.util
import pathlib
import shutil

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]


def _fg():
    spec = importlib.util.spec_from_file_location("feed_guard", HERE / "feed-guard.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


NINE = (
    "🔴 Blocked: none\n🟡 Active: x\n🟢 Done: y\n⚪ Pending: z\n🔧 TOUCHES: none\n🔀 OVERLAP: none\n"
    "📎 FACTS: https://github.com/chidionyema/crew/issues/629#issuecomment-1\n📍 State: none\n"
)


@pytest.mark.skipif(
    shutil.which("opa") is None,
    reason="opa grades the shape; without it the check is BLIND",
)
def test_incident_crew629_a_facts_line_is_a_legal_ninth_line(tmp_path, monkeypatch):
    fg = _fg()
    monkeypatch.setattr(fg, "holders", lambda *a, **k: [])
    feed = tmp_path / "feed.md"
    assert (
        fg.append(
            feed,
            "s1",
            "lane",
            NINE,
            meter="📍 METER: 2026-08-29 $1.00 1 req $1.000/req",
        )
        is None
    )
    assert (
        "📎 FACTS: https://github.com/chidionyema/crew/issues/629" in feed.read_text()
    )


def test_incident_crew629_a_handoff_without_facts_is_noted_not_refused(
    tmp_path, monkeypatch, capsys
):
    fg = _fg()
    monkeypatch.setattr(fg, "holders", lambda *a, **k: [])
    feed = tmp_path / "feed.md"
    body = "🟡 Active: x\n🔧 TOUCHES: none\n🔀 OVERLAP: none\n"
    assert (
        fg.append(
            feed,
            "s1",
            "lane",
            body,
            meter="📍 METER: 2026-08-29 $1.00 1 req $1.000/req",
        )
        is None
    )
    assert "no 📎 FACTS: line" in capsys.readouterr().err
    assert "🟡 Active: x" in feed.read_text()


def test_incident_crew629_the_policy_names_the_facts_mark():
    rego = (HERE / "policy/feed.rego").read_text()
    assert '"📎"' in rego and "max_lines := 9" in rego
