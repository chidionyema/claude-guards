"""Incident crew#273 (founder, 2026-08-26): a session told him to "turn on Remote Control for
all sessions" as step 1 of a founder-facing flow, the day after he ruled the spec vendor
agnostic (LAW 34). vendor-lock-guard.py --files is the CI face of the rule; this drives it
both ways on real files so the guard is an executable spec (R29), not a script with a selftest.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "..", "vendor-lock-guard.py")

MANDATE = ("## Phone path\n\nStep 1: in Claude Code run `/config` and turn on Remote Control "
           "for all sessions. Only you can do it.\n")
NAMING = ("| Anthropic Remote Control | Claude only; no API key (LAW 34). |\n\n"
          "Step 1: the phone sends a Telegram message to the gateway; done when the draft comes back.\n")


def _run(*paths):
    return subprocess.run([sys.executable, GUARD, "--files", *paths], capture_output=True, text=True, check=False)


def test_a_spec_that_makes_a_vendor_channel_mandatory_is_refused(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(MANDATE)
    r = _run(str(f))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Remote Control" in r.stdout


def test_naming_the_vendor_in_a_rejection_table_is_allowed(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(NAMING)
    r = _run(str(f))
    assert r.returncode == 0, r.stdout + r.stderr


def test_selftest_proves_both_ways():
    r = subprocess.run([sys.executable, GUARD, "--selftest"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "7/7 passed" in r.stdout


# cg#177 (2026-08-27 22:05Z, crew-qa run 33121023133): `/config\b` matched the path segment in
# `platform/llm/config.yaml` on crew main's docs/STANDARDS.md:27 and, with `CP4` on the line,
# refused every crew PR. The slash command is still refused; a path is not a command.
PATH_ROW = "| LLM providers | LiteLLM proxy (MIT core) at idp platform/llm/config.yaml; CP4 required |\n"
SLASH_ROW = "Step 1: run /config and turn on Remote Control for all sessions.\n"


def test_a_path_segment_named_config_is_not_the_slash_command(tmp_path):
    f = tmp_path / "STANDARDS.md"
    f.write_text(PATH_ROW)
    r = _run(str(f))
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_bare_slash_command_is_still_refused(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(SLASH_ROW)
    r = _run(str(f))
    assert r.returncode == 1, r.stdout + r.stderr
