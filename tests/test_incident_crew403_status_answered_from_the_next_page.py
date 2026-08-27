"""Incident crew#403 CP6: the founder asked three sessions in one day what is planned, what is
blocking and when; each answered from memory. A status/capabilities/progress/when prompt now
injects the generated page (idp docs/NEXT.md) and its URL; any other prompt injects nothing; a
missing page is BLIND and still names the URL. Rung 4, both ways."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("feed_guard", HERE / "feed-guard.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


PAGE = ("# What is planned\n\n- Checkpoints: **2 BLOCKING**, **4 ACTIVE**, **99 PLANNED** of 105 open\n"
        "- When: **105 NO DATE**, 0 dated\n- Lanes reporting: code (2026-08-27T13:02Z)\n\n| Status | Issue |\n"
        "| BLOCKING | crew#488 | CP2 |\n| PLANNED | crew#7 | CP1 |\n")


def test_incident_crew403_status_prompt_injects_the_page(tmp_path):
    m = _mod(); page = tmp_path / "NEXT.md"; page.write_text(PAGE)
    for prompt in ("Status", "how is progress",
                   # the founder's three verbatim prompts, 2026-08-27 (claude-guards#152 review)
                   "what major capablities and showcase do you have planned",
                   "what capalilities are outstanding or blocking",
                   "nd when to epect",
                   "what next", "whats next"):  # named next* as a stem, 78caaa17 on #153
        out = m.next_answer(prompt, page, "https://x/NEXT.md")
        assert out and "https://x/NEXT.md" in out and "**2 BLOCKING**" in out and "**105 NO DATE**" in out, prompt
        assert "| BLOCKING | crew#488" in out and "| PLANNED |" not in out, "red rows only; the page holds the rest"


def test_incident_crew403_other_prompts_inject_nothing(tmp_path):
    m = _mod(); page = tmp_path / "NEXT.md"; page.write_text(PAGE)
    for prompt in ("merge idp#402", "fix the failing test", "", "the status bar css is wrong"[:0]):
        assert m.next_answer(prompt, page, "https://x/NEXT.md") is None, prompt


def test_incident_crew403_missing_page_is_blind_with_the_url(tmp_path):
    m = _mod()
    out = m.next_answer("Status", tmp_path / "nope.md", "https://x/NEXT.md")
    assert out and "BLIND" in out and "https://x/NEXT.md" in out and "never from memory" in out
