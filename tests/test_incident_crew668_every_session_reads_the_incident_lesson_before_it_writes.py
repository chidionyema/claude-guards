"""crew#668 CP6: the incident ledger is training data. It only trains if every session reads it
at start; a ledger nobody reads is an instrument nobody reads (LAW 28).

Paired controls: ranked classes are injected, unclassified rows are counted but never ranked, a
resolved row is never shown as open, and no data injects nothing (fail open)."""

import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), HERE / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fr = _load("friction-relay")
LEDGER = [
    {
        "id": "I1",
        "classes": ["fix-proved-on-the-wrong-surface"],
        "title": "Otto dark",
        "resolved": "",
    },
    {
        "id": "I0",
        "classes": ["silent-green"],
        "title": "closed",
        "resolved": "2026-08-30T01:26Z",
    },
]
GUARDS = [{"class": "silent-green"}] * 3 + [{"class": "unclassified"}] * 9


def test_the_top_classes_are_ranked_and_injected():
    out = fr.render_incidents({"incidents": fr.summarise_incidents(LEDGER, GUARDS)})
    assert "KEEPS GETTING WRONG" in out
    assert out.index("silent-green") < out.index("fix-proved-on-the-wrong-surface")


def test_an_unclassified_guard_is_counted_but_never_ranked():
    summary = fr.summarise_incidents(LEDGER, GUARDS)
    assert summary["guards"] == 12
    assert "unclassified" not in fr.render_incidents({"incidents": summary})


def test_only_an_unresolved_incident_is_listed_as_open():
    out = fr.render_incidents({"incidents": fr.summarise_incidents(LEDGER, GUARDS)})
    assert "OPEN I1: Otto dark" in out
    assert "OPEN I0" not in out


def test_no_incident_data_injects_nothing():
    assert fr.render_incidents({}) == ""
    assert (
        fr.render_incidents(
            {"incidents": {"classes": [["unclassified", 5]], "open": []}}
        )
        == ""
    )


def test_the_ledger_is_read_from_the_board_repo_not_a_checkout_path():
    src = (HERE / "friction-relay.py").read_text()
    assert "repos/%s/contents" in src and "incidents/LEDGER.jsonl" in src
    assert "dev/code/crew" not in src
