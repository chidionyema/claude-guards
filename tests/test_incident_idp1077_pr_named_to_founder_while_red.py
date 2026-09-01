"""Incident test (rung 4), R61: idp pull request 1077 was named to the founder three
times while its gates were still red. His ruling, 2026-08-31: "looks NEVER tell nne
about pr UNTIL green. Enforce it." pr-green-guard.py refuses a reply that carries a
pull-request URL whose checks are not all green.

Paired controls in one run: a red pull request blocks and a green one passes; a
superseded cancelled run does not shadow its green rerun; a pull request the guard
cannot measure (gh down) passes, because a guard that cannot measure must not block.
"""

import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _guard():
    spec = importlib.util.spec_from_file_location(
        "pr_green_guard", os.path.join(HERE, "pr-green-guard.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


URL = "the change is at https://github.com/o/r/pull/1077"


def test_a_red_pull_request_blocks_and_a_green_one_passes():
    g = _guard()
    red = [{"name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}]
    green = [{"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    assert g.offences(URL, fetch=lambda *_: red), (
        "the 1077 incident replays: red passed"
    )
    assert not g.offences(URL, fetch=lambda *_: green), (
        "a green pull request was blocked"
    )


def test_a_still_running_check_blocks():
    g = _guard()
    pending = [{"name": "ci", "status": "IN_PROGRESS", "conclusion": ""}]
    assert g.offences(URL, fetch=lambda *_: pending), "an in-flight check read as green"


def test_a_superseded_cancelled_run_does_not_shadow_its_green_rerun():
    g = _guard()
    rollup = [
        {"name": "ci", "status": "COMPLETED", "conclusion": "CANCELLED"},
        {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"},
    ]
    assert not g.offences(URL, fetch=lambda *_: rollup), (
        "statusCheckRollup keeps one entry per run; the last run per name is the verdict"
    )


def test_the_guard_fails_open_when_it_cannot_measure():
    g = _guard()
    assert not g.offences(URL, fetch=lambda *_: None), (
        "gh down must not block (LAW 38): a guard that cannot measure is an outage"
    )


def test_a_reply_with_no_pull_url_never_calls_gh():
    g = _guard()

    def boom(*_):
        raise AssertionError("gh was called for a reply with no pull-request URL")

    assert not g.offences("INVENTORY: portal doors fixed.", fetch=boom)


def test_selftest_is_green_offline():
    out = subprocess.run(
        [sys.executable, os.path.join(HERE, "pr-green-guard.py"), "--selftest"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert out.returncode == 0, out.stdout + out.stderr
