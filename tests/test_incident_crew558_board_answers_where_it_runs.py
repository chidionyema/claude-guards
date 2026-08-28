"""crew#558, 2026-08-28. The founder asked where the estate actually runs and nothing answered.

Verbatim: "we need to get a bearing on where we are whats on mac vs whats on cluster and cloud,
whats a dev env and whats cloud env, we need to be able to seamlessly work from anywhere". The
board had rows for what is broken and what is waiting on him, and no row for where any of it
lives -- so the answer had to be assembled by hand each time he asked, which is the friction the
board exists to remove.

The shape of the answer on the day he asked it: the cluster was reachable from CI (login-drill
green 09:29Z) and NOT from his Mac (the kubeconfig execs `oci` with no --profile, ~/.oci/config
has no DEFAULT profile, and both session tokens had expired), eight daemons and the Dagster
scheduler ran on the laptop, and 98.7% of the estate's own data map was a walk of the laptop's
disk.

What this file pins is not those numbers -- they are supposed to move -- but the two ways the row
set can go quietly wrong: a probe that fails reporting a comfortable zero instead of UNKNOWN
(board rule 1), and the cluster row being pointed at the wrong repository, which is the exact
defect that once made every workflow row on this board read UNKNOWN.
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _fb():
    spec = importlib.util.spec_from_file_location("fb", ROOT / "founder_board.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["fb"] = m
    spec.loader.exec_module(m)
    return m


fb = _fb()


def test_the_board_carries_a_where_it_runs_section():
    titles = [t for t, _ in fb.COLLECTORS]
    assert any("Where it runs" in t for t in titles), (
        "the founder's bearing question has no section on the board: " + str(titles[:3]))


def test_the_ci_row_asks_the_repo_the_cluster_workflows_live_in():
    """The platform workflows are in idp; the product is in GH_REPO. Asking the wrong repo is how
    every workflow row on this board once read UNKNOWN while gh worked fine in a terminal."""
    argv = fb._gh_runs_cmd("login-drill.yml", 5, fb.IDP_REPO)
    assert argv[argv.index("--repo") + 1] == fb.IDP_REPO
    assert "idp" in fb.IDP_REPO
    assert argv[-2:] == ["--workflow", "login-drill.yml"], argv


def test_the_default_repo_is_unchanged_for_every_existing_caller():
    """Adding the parameter must not move any existing row. LAW 38: a guard -- or a change --
    that breaks correct work is an outage."""
    argv = fb._gh_runs_cmd("deploy-web.yml", 8)
    assert argv[argv.index("--repo") + 1] == fb.GH_REPO


@pytest.mark.parametrize("probe", ["_cluster_from_here", "_cluster_from_ci",
                                   "_runs_on_this_laptop", "_map_is_a_disk_scan"])
def test_a_probe_that_cannot_run_reports_unknown_and_never_a_zero(probe, monkeypatch):
    """Board rule 1, the one this estate has already paid for: a dead probe and a clean probe
    both find nothing, and only one of them is good news."""
    monkeypatch.setattr(fb, "sh", lambda *a, **k: (127, "", "FileNotFoundError: no such tool"))
    monkeypatch.setattr(fb, "_gh_runs", lambda *a, **k: None)
    monkeypatch.setattr(fb.os.path, "exists", lambda p: False)
    monkeypatch.setattr(fb.os.path, "isdir", lambda p: False)
    row = getattr(fb, probe)()
    assert row.state in (fb.UNKNOWN, fb.BAD), f"{probe} reported {row.state} when it could not run"
    assert row.value != "0" and row.value != 0, f"{probe} reported a zero it did not measure"
    assert row.detail or row.value == "UNKNOWN", f"{probe} gave no reason"


def test_every_bearing_row_carries_the_command_that_produced_it():
    """A row nobody can re-run is prose. Every row on this board carries its own receipt."""
    for row in fb.collect_bearing():
        assert row.command, f"{row.label} carries no command"
        assert row.measured_at > 0
