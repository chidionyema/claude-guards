"""Incident crew#13 (2026-08-26): claude-guards#80 moved eight committed plists off
~/.hermes. The live plists were not re-rendered, and tracked.py --sync then copied the stale
live plists back over the merged fix and pushed to main as 442675d. Rule: a manifest entry
with a `generated` key is sourced from the repo, so tracked.py never mirrors it live -> repo;
it reports the drift instead. An entry without `generated` still mirrors. Rung 4 (incident)."""
import importlib.machinery
import importlib.util
import os

HERE_DIR = os.path.dirname(os.path.abspath(__file__))


def _tracked():
    ld = importlib.machinery.SourceFileLoader("tracked_gen", os.path.join(HERE_DIR, "tracked.py"))
    spec = importlib.util.spec_from_loader("tracked_gen", ld)
    mod = importlib.util.module_from_spec(spec)
    ld.exec_module(mod)
    return mod


def _entry(tmp, name, generated):
    live, repo = tmp / f"{name}-live", tmp / f"{name}-repo"
    live.mkdir(); repo.mkdir()
    (live / "job.plist").write_text("<string>/Users/me/.hermes/scripts/x.py</string>")
    (repo / "job.plist").write_text("<string>/Users/me/.claude/scripts/estate/x.py</string>")
    e = {"live": str(live), "repo": name, "repo_abs": str(repo), "glob": "*.plist"}
    if generated:
        e["generated"] = "jobs/render.py --write"
    return e, repo / "job.plist"


def test_a_generated_entry_is_reported_not_mirrored(tmp_path):
    t = _tracked()
    e, committed = _entry(tmp_path, "gen", generated=True)
    before = committed.read_text()
    assert t.pull_one(e) == (0, 0, 0)
    assert committed.read_text() == before
    assert t.STALE_GENERATED and t.STALE_GENERATED[0][0] == "gen"
    assert t.STALE_GENERATED[0][2] == ["job.plist"]


def test_a_plain_entry_still_mirrors(tmp_path):
    t = _tracked()
    e, committed = _entry(tmp_path, "plain", generated=False)
    assert t.pull_one(e) == (0, 0, 1)
    assert ".hermes" in committed.read_text()
    assert t.STALE_GENERATED == []


def test_the_launchagents_entry_is_marked_generated():
    import json
    m = json.load(open(os.path.join(HERE_DIR, "tracked.json")))
    e = next(x for x in m if x["repo"] == "launchagents")
    assert e.get("generated")
