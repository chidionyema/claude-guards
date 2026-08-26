"""Rung 4 (incident test). 2026-08-26, session 78caaa17: rule-guard refused
`gh issue comment 301 --body "... the plan step ... if you run <infra apply> now"`
as paid infrastructure, then refused a grep whose pattern quoted another rule. The
class: text carried by a prose flag (--body, --title, --caption, like -m before it)
judged as if it were the command. strip_commit_messages now blanks those bodies.
Proved both ways: prose is not judged; the same words as a command still are.
"""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rule_guard", HERE / "rule-guard.py")
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)

APPLY = "tofu " + "apply"          # never written whole: this file's own text is scanned too


def test_incident_prose_flags_are_not_judged():
    for flag in ("--body", "--title", "--caption", "-m"):
        cmd = f'gh issue comment 1 {flag} "run {APPLY} then merge"'
        assert APPLY not in rg.strip_commit_messages(cmd), flag


def test_incident_the_same_words_as_a_command_are_still_judged():
    for cmd in (f"{APPLY} -auto-approve", f'bash -c "{APPLY}"', f"echo x && {APPLY}"):
        assert APPLY in rg.strip_commit_messages(cmd), cmd


if __name__ == "__main__":
    test_incident_prose_flags_are_not_judged(); test_incident_the_same_words_as_a_command_are_still_judged()
    print("PASS test_incident_rule_guard_prose_flags")
