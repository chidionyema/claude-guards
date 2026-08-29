"""Incident 2026-08-29: the staging-cluster discussion the founder pasted existed only in transcript
files; a session searched ~4000 .jsonl files to answer "what did we discuss yesterday". Founder:
"we should not be looking for infra discussions". The guard writes a pasted document to git on arrival."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "founder-doc-capture.py"
SETTINGS = Path(__file__).resolve().parents[2] / "settings.json"


def load(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ESTATE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("fdc", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    monkeypatch.setattr(
        mod,
        "commit",
        lambda paths, push=True: mod.__dict__.setdefault("committed", []).extend(paths),
    )
    return mod


def run_hook(mod, prompt, tmp_path):
    payload = {"prompt": prompt, "session_id": "s1", "cwd": str(tmp_path)}
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_ESTATE_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    ).stdout


def test_a_pasted_document_becomes_a_file_the_session_is_told_about(
    tmp_path, monkeypatch
):
    mod = load(tmp_path, monkeypatch)
    doc = "The Verification Plane\n\n" + ("Status: design spec. " * 120)
    assert mod.is_document(doc)
    out = run_hook(mod, doc, tmp_path)
    files = list((tmp_path / "docs" / "founder").glob("*.md"))
    assert len(files) == 1, "the pasted document was not written"
    assert files[0].read_text().rstrip().endswith("Status: design spec.")
    assert "the-verification-plane" in files[0].name
    assert str(files[0]) in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_a_save_order_captures_the_message_even_when_short(tmp_path, monkeypatch):
    mod = load(tmp_path, monkeypatch)
    assert mod.is_document(
        "save this doc in line with our doc standards: staging is a namespace"
    )
    assert mod.is_document("document this decision: prod is 6 cores")


def test_harness_text_and_short_chat_are_never_documents(tmp_path, monkeypatch):
    mod = load(tmp_path, monkeypatch)
    assert not mod.is_document("<task-notification>" + "x" * 3000)
    assert not mod.is_document("Stop hook feedback: " + "x" * 3000)
    assert not mod.is_document("why is it in abyss")
    assert not mod.is_document("/compact")


def test_the_same_document_is_written_once(tmp_path, monkeypatch):
    mod = load(tmp_path, monkeypatch)
    doc = "Same doc\n" + "y " * 1000
    run_hook(mod, doc, tmp_path)
    run_hook(mod, doc, tmp_path)
    assert len(list((tmp_path / "docs" / "founder").glob("*.md"))) == 1


def test_the_hook_is_wired_on_every_prompt():
    cfg = json.loads(SETTINGS.read_text())
    cmds = [
        h["command"] for grp in cfg["hooks"]["UserPromptSubmit"] for h in grp["hooks"]
    ]
    assert any("founder-doc-capture.py" in c for c in cmds), (
        "founder-doc-capture.py is not a UserPromptSubmit hook"
    )
