"""crew#423 (rung 4): the enforcement map graded LAW 31 'the founder does not run scripts' as
absent: no guard. founder-imperative-guard.py is the guard. The rule, both ways: a reply line
above the fold that opens with run/type/paste/open/click is refused; Use:, FOUNDER ACTION: and
STAGED: lines and everything below the fold are not."""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _mod():
    spec = importlib.util.spec_from_file_location("fig", os.path.join(HERE, "founder-imperative-guard.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_chore_line_is_refused_and_format_lines_are_not():
    m = _mod()
    assert m.offences("DONE: fixed.\nRun `make x` and paste the output.\n") == ["Run `make x` and paste the output."]
    assert m.offences("1. Open the console and click Approve.") != []
    assert m.offences("You'll need to run `terraform apply` once.") != []
    assert m.offences("Use: `gh workflow run x.yml`\nFOUNDER ACTION: tap the YubiKey.\n"
                      "STAGED: rotating. Reply 'hold'.\nThe job runs itself.\n---\nrun `pytest`") == []


def test_guard_is_wired_on_stop():
    s = json.load(open(os.path.join(HERE, "settings", "settings.json")))
    cmds = [h.get("command", "") for grp in s["hooks"]["Stop"] for h in grp.get("hooks", [])]
    assert any("founder-imperative-guard.py" in c for c in cmds)


def test_selftest_passes():
    assert _mod().selftest() == 0
