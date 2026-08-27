"""Incident crew#73: 902 close-guard observations and 1,526 stuck_detector session rows had no
time field, so the warehouse held them with at=NULL and "is the guard firing more than last
week" had no answer. The rule: every row these two producers write carries an ISO-8601 UTC time
on a key the collector reads (`at` or `ts`) and a `kind` that names its shape. Rung 4.
"""
import json
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_close_guard_observe_row_is_stamped(tmp_path):
    src = (HERE / "close-guard.py").read_text()
    m = re.search(r'line = json\.dumps\(\{(.*?)\}\)', src, re.S)
    assert m and '"at":' in m.group(1) and '"kind": "observe"' in m.group(1)


def test_stuck_detector_session_rows_are_stamped(tmp_path):
    proj = tmp_path / "projects" / "-x"
    proj.mkdir(parents=True)
    now = __import__("time").time()
    rec = {"type": "user", "timestamp": __import__("datetime").datetime.utcfromtimestamp(now - 5).isoformat() + "Z",
           "message": {"role": "user", "content": "hi"}, "cwd": "/x"}
    (proj / "sess1.jsonl").write_text(json.dumps(rec) + "\n")
    out = subprocess.run([sys.executable, str(HERE / "stuck_detector.py"), "--json", "--all", "--no-state", "--projects", str(tmp_path / "projects"),
                          "--state-file", str(tmp_path / "state.json")], capture_output=True, text=True,
                         env={**os.environ, "HOME": str(tmp_path)})
    rows = [json.loads(line) for line in out.stdout.splitlines() if line.startswith("{")]
    assert rows, out.stderr[-400:]
    for r in rows:
        assert ISO.match(r["at"]) and r["kind"] == "session", r


def test_tick_header_names_its_shape():
    # crew#73 REWORK (claude-guards#123 review): run the header lines the shell emits and parse
    # the row. sources.json declares stuck_detector time_field "at"; a header keyed only "ts"
    # is an at-IS-NULL row that crew#418's null_time_verdict fails on every run.
    sh = (HERE / "stuck_detector_tick.sh").read_text().splitlines()
    header = [ln for ln in sh if ln.startswith("TICK_AT=") or ln.startswith("printf '{")]
    assert len(header) == 2, header
    out = subprocess.run(["bash", "-c", "RC=0; N=0; " + "\n".join(header)], capture_output=True, text=True, check=True)
    row = json.loads(out.stdout)
    assert ISO.match(row["at"]) and row["kind"] == "tick", row
