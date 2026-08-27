"""crew#527 CP4 (founder 2026-08-27: "we have many features half done"): 123 of 187 open crew issues
had no checklist and 42 had no lane, so the finish-first rank could not see what was half done.
Every issue ticket-gate opens now carries a lane label and the three-box minimum."""
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ticket_gate", HERE / "ticket-gate.py")
tg = importlib.util.module_from_spec(spec)
sys.modules["ticket_gate"] = tg
spec.loader.exec_module(tg)
import issue_dod as dod  # noqa: E402


def test_the_three_boxes_are_build_prove_and_founder_used_it():
    assert dod.has_dod(dod.DOD_BOXES)
    for word in ("Built", "Proved", "Founder used it"):
        assert word in dod.DOD_BOXES


def test_a_body_with_fewer_than_three_boxes_is_not_done_shaped():
    assert not dod.has_dod("- [ ] one\n- [x] two\n")
    assert not dod.has_dod("")
    assert dod.has_dod("- [ ] a\n- [x] b\n- [ ] c\n")


def test_lane_comes_from_the_working_directory_and_never_guesses():
    assert dod.lane_for("/Users/x/dev/code/idp/.wt-abc") == "lane:platform"
    assert dod.lane_for("/Users/x/dev/code/hermes-v2") == "lane:agents"
    assert dod.lane_for("/Users/x/dev/code/prospector-main/app") == "lane:money"
    assert dod.lane_for("/Users/x/dev/code") == "lane:unsorted"


def test_the_opened_issue_carries_both(monkeypatch, tmp_path):
    seen = {}

    class R:
        returncode = 0
        stdout = "https://github.com/chidionyema/crew/issues/999\n"
        stderr = ""

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return R()

    monkeypatch.setattr(tg.subprocess, "run", fake_run)
    monkeypatch.setattr(tg, "write_bind", lambda sid, data: None)
    assert tg.open_issue("sess1234", "make the board assign", "/Users/x/dev/code/crew") == 0
    argv = seen["argv"]
    body = argv[argv.index("--body") + 1]
    assert dod.has_dod(body)
    assert "lane:process" in argv
