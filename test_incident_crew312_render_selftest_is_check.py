"""crew#312: jobs.json drifted from 23 live plists and nothing said so, because render.py --check
only ran when a person typed it. Rule: `render.py --selftest` is the check under the flag
estate-selftest.py discovers, exit 0 in step and exit 1 on drift. Hermetic: renders into a temp
directory and points the module's LIVE at it, so it holds on CI with no ~/Library/LaunchAgents."""
import importlib.util
import pathlib
import plistlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("render_312", HERE / "jobs" / "render.py")
assert spec is not None and spec.loader is not None
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def _run(argv):
    old = sys.argv
    sys.argv = ["render.py", *argv]
    try:
        return R.main()
    finally:
        sys.argv = old


def _live_dir(home):
    d = pathlib.Path(tempfile.mkdtemp(prefix="crew312-"))
    with open(R.MANIFEST) as fh:
        import json
        jobs = json.load(fh)
    for label, job in jobs.items():
        with open(d / f"{label}.plist", "wb") as fh:
            plistlib.dump(R.render(job, home), fh)
    return d


def test_selftest_is_zero_when_manifest_matches_live(capsys):
    R.LIVE = str(_live_dir("/home/estate"))
    assert _run(["--selftest", "--home", "/home/estate"]) == 0
    assert "in step:" in capsys.readouterr().out


def test_selftest_is_nonzero_on_drift(capsys):
    R.LIVE = str(_live_dir("/home/estate"))
    assert _run(["--selftest", "--home", "/home/elsewhere"]) == 1
    assert "differs from the manifest" in capsys.readouterr().out
