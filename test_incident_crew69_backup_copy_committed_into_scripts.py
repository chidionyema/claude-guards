"""crew#69: a backup copy of a script was committed into ~/.claude/scripts (context-guard-hook.py.bak-20260806).

Class: a scratch copy in a tracked directory. .gitignore refused new ones; a file tracked before the
ignore stays tracked forever, so the rule is asserted over `git ls-files`, not over the ignore file.
"""
import fnmatch
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
BACKUP_PATTERNS = ("*.bak", "*.bak-*", "*.bak.*", "*.before-*", "*.orig", "*~")


def backup_copies(paths):
    return sorted(p for p in paths if any(fnmatch.fnmatch(pathlib.PurePath(p).name, g) for g in BACKUP_PATTERNS))


def test_no_tracked_file_is_a_backup_copy():
    tracked = subprocess.run(["git", "ls-files"], cwd=HERE, capture_output=True, text=True, check=True).stdout.split()
    assert backup_copies(tracked) == [], "backup copies tracked in git; git rm them, history already holds the original"


def test_the_rule_refuses_the_instance_and_permits_a_real_script():
    # both ways in one run: the file that opened crew#69 is refused, its live sibling is not
    assert backup_copies(["context-guard-hook.py.bak-20260806", "context-guard-hook.py"]) == ["context-guard-hook.py.bak-20260806"]
    assert backup_copies(["memory-loop.py.before-law16-cap", "jargon-guard.py.bak.20260822"]) == [
        "jargon-guard.py.bak.20260822", "memory-loop.py.before-law16-cap"]
    assert backup_copies(["rule-guard.py", "tests/conftest.py", "policy/reply.rego"]) == []
