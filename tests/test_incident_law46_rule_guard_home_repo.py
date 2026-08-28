"""Incident test, LAW 46: rule-guard.py hardcoded one Mac's absolute path
(`/Users/chidionyema/Documents/code/prospector`) into `_HOME_REPO`. On any other
machine or checkout that path is simply not there, and worse -- if it existed for a
different user it would silently grade the wrong tree. LAW 46: no file names where
the checkout, the home directory or the machine lives as a literal.

Two angles (LAW 15): the source has no `/Users/` literal left anywhere, and the
resolver actually honours the env var it claims to read.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULE_GUARD = os.path.join(HERE, "rule-guard.py")


def test_no_users_literal_in_rule_guard():
    with open(RULE_GUARD) as f:
        src = f.read()
    hits = re.findall(r"/Users/[^\s'\")]*", src)
    assert not hits, f"rule-guard.py still hardcodes a machine path: {hits}"


def test_home_repo_honours_env_var(tmp_path):
    fake_repo = tmp_path / "prospector"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()

    env = dict(os.environ)
    env["PROSPECTOR_REPO"] = str(fake_repo)
    r = subprocess.run(
        [sys.executable, "-c",
         "import os; os.environ.setdefault('PROSPECTOR_REPO', '');"
         "import importlib.util as u;"
         f"spec = u.spec_from_file_location('rule_guard', {RULE_GUARD!r});"
         "m = u.module_from_spec(spec); spec.loader.exec_module(m);"
         "print(m._HOME_REPO)"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == str(fake_repo), r.stdout + r.stderr


def test_home_repo_falls_back_without_env_var(tmp_path, monkeypatch):
    env = dict(os.environ)
    env.pop("PROSPECTOR_REPO", None)
    env["HOME"] = str(tmp_path)  # no ~/Documents/code/prospector under a fresh HOME
    r = subprocess.run(
        [sys.executable, "-c",
         "import os;"
         "import importlib.util as u;"
         f"spec = u.spec_from_file_location('rule_guard', {RULE_GUARD!r});"
         "m = u.module_from_spec(spec); spec.loader.exec_module(m);"
         "print(m.REPO)"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    # Nonexistent _HOME_REPO under the fresh HOME -> REPO falls back to os.getcwd().
    assert r.stdout.strip() == os.getcwd(), r.stdout + r.stderr
