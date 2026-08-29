"""LAW 51 enforced before execution, not graded after it (founder 2026-08-29 21:5xZ).

"i need to see enforcement on optimised plan, its not negotiable ... sometimes the problem has
already been solved, they just didn't follow laws to check is there something already existing".
The rego `optimised_plan` reads the PR body at the end; plan-gate refuses the first mutating
call of a session with no counted plan on disk.
"""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
GOOD = (
    "Existing: `ticket-gate.py` binds a ticket; searched `grep -ln plan *.py`\n"
    "Naive: 9 steps, 6 round trips\nBottleneck: the live run\n"
    "Optimised: 9 -> 4, 6 -> 2; cut: separate write steps, one heredoc\nVerify: `pytest -q`\n"
)


def load(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAN_GATE_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("plan_gate", HERE / "plan-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_plan_refuses_the_first_mutating_call_and_names_the_five_lines(
    tmp_path, monkeypatch
):
    m = load(tmp_path, monkeypatch)
    code, msg = m.verdict("Write", {"file_path": "/repo/x.py"}, "sid1", True)
    assert code == 2
    for lab in ("Existing:", "Naive:", "Bottleneck:", "Optimised:", "Verify:"):
        assert lab in msg


def test_a_counted_plan_lets_the_call_through(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    m.PLANS.mkdir(parents=True)
    m.plan_path("sid1").write_text(GOOD)
    assert m.verdict("Write", {"file_path": "/repo/x.py"}, "sid1", True) == (0, "")


def test_an_uncounted_optimised_line_is_not_a_plan(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    m.PLANS.mkdir(parents=True)
    m.plan_path("sid1").write_text(
        GOOD.replace(
            "9 -> 4, 6 -> 2; cut: separate write steps, one heredoc",
            "we made it faster",
        )
    )
    code, msg = m.verdict("Bash", {"command": "git commit -m x"}, "sid1", True)
    assert code == 2 and "cut:" in msg


def test_writing_the_plan_itself_is_always_allowed(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    assert (
        m.verdict("Write", {"file_path": str(m.plan_path("sid1"))}, "sid1", True)[0]
        == 0
    )
    assert (
        m.verdict(
            "Bash", {"command": f"cat > {m.plan_path('sid1')} <<EOF"}, "sid1", True
        )[0]
        == 0
    )


def test_reads_and_the_founders_own_shell_are_never_gated(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    assert m.verdict("Bash", {"command": "ls"}, "sid1", False)[0] == 0
    assert m.verdict("Write", {"file_path": "/repo/x.py"}, "", True)[0] == 0


def test_hook_is_wired_before_ticket_gate_on_every_mutating_tool():
    s = json.loads((HERE / "settings" / "settings.json").read_text())
    wired = {
        m["matcher"]
        for m in s["hooks"]["PreToolUse"]
        for h in m["hooks"]
        if h["command"].endswith("plan-gate.py")
    }
    assert "Bash" in wired and any("Edit" in w and "Write" in w for w in wired), wired
