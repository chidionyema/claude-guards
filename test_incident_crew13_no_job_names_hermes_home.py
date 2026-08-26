"""Incident crew#13 (2026-08-26): ~/.hermes was retired on 2026-08-22, but eight loaded launchd
jobs still executed ~/.hermes/scripts/launchd_receipt.py through the symlink, so the tree could
not be renamed. Rule: no job declaration in jobs/jobs.json and no tracked plist names a path
under ~/.hermes. ai.hermes.gateway is the one exception: it is retired and never loaded.
Rung 4 (incident). Both ways: the live files pass, a plist text naming ~/.hermes is caught."""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RETIRED = {"ai.hermes.gateway"}
PAT = re.compile(r"/\.hermes(/|\b)")


def _offenders(texts: dict) -> list:
    return sorted(label for label, text in texts.items() if PAT.search(text))


def _job_texts() -> dict:
    with open(os.path.join(HERE, "jobs", "jobs.json")) as f:
        jobs = json.load(f)
    return {label: json.dumps(job) for label, job in jobs.items() if label not in RETIRED}


def _plist_texts() -> dict:
    out = {}
    for p in glob.glob(os.path.join(HERE, "launchagents", "*.plist")):
        label = os.path.basename(p)[: -len(".plist")]
        if label in RETIRED:
            continue
        with open(p) as f:
            out[label] = f.read()
    return out


def test_no_job_declaration_names_hermes_home():
    assert _offenders(_job_texts()) == []


def test_no_tracked_plist_names_hermes_home():
    assert _offenders(_plist_texts()) == []


def test_the_check_sees_a_hermes_path():
    texts = {"bad": "<string>/Users/me/.hermes/scripts/launchd_receipt.py</string>",
             "good": "<string>/Users/me/.claude/scripts/estate/launchd_receipt.py</string>"}
    assert _offenders(texts) == ["bad"]


def test_wrapper_writes_under_estate_not_hermes():
    with open(os.path.join(HERE, "estate", "launchd_receipt.py")) as f:
        src = f.read()
    line = next(l for l in src.splitlines() if l.startswith("RECEIPTS ="))
    assert "~/.estate/state/capability_receipts.jsonl" in line and not PAT.search(line)
