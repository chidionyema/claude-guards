"""Incident test (rung 4), crew#64: ~/.estate/.gitignore line 7 is "*", and a commit of three
files silently dropped scripts/inventory.py while reporting success. in-git.py reported an
executed, untracked file as "not in git" with no reason, so the refusing rule was never seen.

Paired control in one run: a file an ignore rule refuses names the rule; a file the same
repo admits names nothing.
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ingit():
    sys.path.insert(0, HERE)
    spec = importlib.util.spec_from_file_location("in_git", os.path.join(HERE, "estate", "in-git.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_incident_crew64_refused_file_names_the_rule_and_admitted_file_does_not(tmp_path):
    repo = tmp_path / "estate"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("*\n!.gitignore\n!guards/\n!guards/**\n")
    (repo / "scripts").mkdir()
    (repo / "guards").mkdir()
    refused = repo / "scripts" / "inventory.py"
    admitted = repo / "guards" / "hook"
    refused.write_text("print()\n")
    admitted.write_text("#!/bin/sh\n")
    mod = _ingit()
    why = mod.refused_by(str(refused))
    assert "refused by" in why and ".gitignore:1 `*`" in why, why
    assert mod.refused_by(str(admitted)) == ""
