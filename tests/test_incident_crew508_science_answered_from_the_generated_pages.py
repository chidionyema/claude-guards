"""Incident crew#508 CP5: the founder said "when I say science I need to see progress across all
lanes simultaneously" and the session answered from memory. A science/research/lanes prompt now
injects the Lanes table rows and the Outward/Inward grades from the generated pages with their
URL; any other prompt injects nothing; a missing page is BLIND and still names the URL."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("feed_guard", HERE / "feed-guard.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SHOWCASE = ("# Science\n\n## Lanes\n\n| Lane | Facts, 24h | Checkpoints, 24h | Grade | Sources counted |\n|---|---:|---:|---|---|\n"
            "| portal | 0 | 0 | BLIND | estate_registry |\n| code | 29548 | 0 | GAP | ships |\n| x | y |\n")
GRADE = ("# Research\n\n| Direction | Grade | One sentence |\n|---|---|---|\n| Outward | **ELITE** | 25 of 25 |\n"
         "| Inward | **GAP** | foresight trained; 0 of 11 scored |\n| RED 30d | 2026-07-28 | crew#247 |\n| Questions asked | 25 |\n")


def _pages(tmp_path):
    (tmp_path / "SHOWCASE.md").write_text(SHOWCASE)
    (tmp_path / "RESEARCH-GRADE.md").write_text(GRADE)
    return tmp_path


def test_incident_crew508_science_prompt_injects_lanes_and_grades(tmp_path):
    m = _mod()
    d = _pages(tmp_path)
    for prompt in ("science", "how is our general purpse reseach cpapbility",  # founder, 2026-08-27, verbatim
                   "science covervs everythig so when i say science i need to see progress across al lanes",
                   "also data and nachie learning lane"[:0] or "data science lane", "how are the lanes"):
        out = m.science_answer(prompt, d, "https://x/science")
        assert out and "https://x/science/SHOWCASE.md" in out and "| portal | 0 | 0 | BLIND" in out, prompt
        assert "| Outward | **ELITE**" in out and "| Inward | **GAP**" in out and "| RED 30d" in out, prompt
        assert "| x | y |" not in out and "| Questions asked" not in out, "graded rows only; the page holds the rest"


def test_incident_crew508_other_prompts_inject_nothing(tmp_path):
    m = _mod()
    d = _pages(tmp_path)
    for prompt in ("merge idp#402", "fix the failing test", "", "Status"):
        assert m.science_answer(prompt, d, "https://x/science") is None, prompt


def test_incident_crew508_missing_page_is_blind_with_the_url(tmp_path):
    m = _mod()
    out = m.science_answer("science", tmp_path / "nope", "https://x/science")
    assert out and out.count("BLIND") == 2 and "https://x/science/RESEARCH-GRADE.md" in out and "never from memory" in out
