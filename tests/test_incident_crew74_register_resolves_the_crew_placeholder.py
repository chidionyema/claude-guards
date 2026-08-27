"""crew#74 row 1: the export-database drill lives in the crew checkout, and
run.py only knew {HERE}, {HOME} and {IDP}, so a crew-side drill would have had
to name the checkout as a literal path (LAW 46). Rule: {CREW} in a register
command resolves from CREW_DIR, and the registered drill runs through it.
Rung 4, both ways: a fake crew tree passes, an empty one fails."""
import json
import os
import stat
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "drills"))
import run as drills_run  # noqa: E402


def _entry():
    reg = drills_run.load()
    [d] = [d for d in reg["drills"] if d["id"] == "export-database"]
    assert all("{CREW}" in c for c in d["cmd"]), d["cmd"]
    return d


def test_crew_placeholder_resolves_from_crew_dir_both_ways(tmp_path, monkeypatch):
    monkeypatch.setattr(drills_run, "STATE", str(tmp_path / "drills.jsonl"))
    monkeypatch.setattr(drills_run, "LOGS", str(tmp_path / "logs"))
    crew = tmp_path / "crew"
    (crew / ".venv" / "bin").mkdir(parents=True)
    (crew / "science").mkdir()
    py = crew / ".venv" / "bin" / "python"
    py.write_text("#!/bin/sh\ntest -f \"$1\" && echo PASS || { echo FAIL; exit 1; }\n")
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CREW_DIR", str(crew))
    d = _entry()

    rec = drills_run.run_one(d)
    assert rec["status"] == "FAIL" and rec["rc"] == 1, rec  # no export_drill.py in this tree yet

    (crew / "science" / "export_drill.py").write_text("")
    rec = drills_run.run_one(d)
    assert rec["status"] == "PASS" and rec["note"] == "PASS", rec
    rows = [json.loads(line) for line in open(tmp_path / "drills.jsonl")]
    assert [r["status"] for r in rows] == ["FAIL", "PASS"]
