"""Incident test (rung 4): crew#526: the board's Closes-when allow-list could not spell a single
live datamap row, so the nightly close turn ran nothing and the open count never moved.

Measured on 2026-08-28 from science/closer.jsonl, the only production turn so far:
`{"open": 192, "closed": 0, "ran": 2, "refused": 2, "no_rule": 183,
  "by_rule": {"closes-when": 0, "all-ticked": 0}}` — and the two refusals in
~/.claude/state/ledger.jsonl were crew#535 (a shell pipeline, correctly refused) and crew#533,
`python3 science/datamap.py --row mac/*state/pi-bridge-runs*`, which names its own registry row and
was refused only because the grammar `[A-Za-z0-9_.-]+` has neither `/` nor `*`. Every one of the 60
keys in science/verdicts.json carries `/`; most carry `*`. The allow-list was a closed door.

Proved both ways: every live row key is accepted, and a shell metacharacter, a parent directory,
another script and an over-long line are still refused and still never executed.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import estate_board
from estate_board import ALLOWED_CLOSES_WHEN, MAX_CLOSES_WHEN, close_pass


@pytest.fixture(autouse=True)
def ledger_is_a_tmp_file(tmp_path, monkeypatch):
    """crew#407 in spirit: a test never writes the estate's own ledger. close_pass appends a
    `closed`/`refused` row for every issue it sees, and these issue numbers are fixtures."""
    monkeypatch.setattr(estate_board, "LEDGER", tmp_path / "ledger.jsonl")

# Frozen copy of every row key in chidionyema/crew science/verdicts.json on 2026-08-28. Frozen, not
# read, so this test asserts something real on a machine with no crew checkout. Refresh with:
#   python3 -c "import json;print([e['key'] for e in json.load(open('science/verdicts.json'))['entries']])"
LIVE_ROW_KEYS = (
    "mac/*science/warehouse.db*",
    "mac/*.claude/state/toolguard*",
    "mac/*experience_graph.db*",
    "mac/*state/coord/jobs.sqlite*",
    "mac/*.claude/directives*",
    "mac/*state/prompt-ledger*",
    "mac/*jobs/*",
    "mac/*estate-board.jsonl*",
    "mac/*estate-worktr*",
    "mac/*founder-actio*",
    "act/revenue",
    "act/agent_decisions",
    "act/research",
    "act/task_outcome",
    "act/run_duration",
    "act/guard_outcome",
    "act/model_routing",
    "act/context_waste",
    "mac/scheduled_job/*",
    "mac/scheduled_job/*",
    "mac/guard/*",
    "mac/listener/port-3210",
    "mac/listener/*",
    "mac/listener/*",
    "mac/listener/*",
    "mac/repo/*ARCHIVED*",
    "mac/repo/*",
    "mac/drill/*",
    "mac/data/*dagster/history/runs/*",
    "mac/data/*dagster*",
    "mac/data/*healthchecks/data/hc.sqlite",
    "mac/data/*temporal/dev.db",
    "mac/data/*sovereign/budget.db",
    "mac/ledger/*capability_receipts.jsonl",
    "warehouse/*",
    "cluster/UNPARSEABLE/*",
    "cluster/llm/Deployment/litellm/port/4000",
    "cluster/*/HelmRelease/*",
    "cluster/*/Kustomization/*",
    "cluster/*/GitRepository/*",
    "cluster/*/Alert/*",
    "cluster/*/Provider/*",
    "cluster/*/Namespace/*",
    "cluster/*/ConfigMap/*",
    "cluster/*/PolicyException/*",
    "cluster/*/ExternalSecret/*",
    "cluster/*",
    "cluster_live/*",
    "endpoint/*",
    "hook/*",
    "mcp/*",
    "github/repo/*",
    "github/workflow/*",
    "transcript/*",
    "mac/*science/transcripts.db*",
    "mac/data/~/.estate/healthchecks/hc.sqlite",
    "mac/ledger/~/.claude/state/hook-outcomes.jsonl",
    "mac/ledger/*runaway-reaper*",
    "mac/*.claude/logs/consult.jsonl*",
    "mac/*state/pi-bridge-runs*",
)

# The registry is the source of truth; when it is on this machine the frozen copy is checked
# against it, so the two can never quietly drift apart.
LIVE_VERDICTS = os.environ.get(
    "ESTATE_DATAMAP_VERDICTS", os.path.expanduser("~/dev/code/crew/science/verdicts.json"))


def _line(key):
    return f"python3 science/datamap.py --row {key}"


def test_every_live_datamap_row_key_can_be_written_as_a_closes_when_line():
    refused = [k for k in LIVE_ROW_KEYS if not ALLOWED_CLOSES_WHEN.match(_line(k))]
    assert refused == [], f"the board cannot run its own registry rows: {refused[:5]}"
    assert len(LIVE_ROW_KEYS) >= 60, "the frozen key set was emptied; the sweep would prove nothing"


def test_the_row_crew533_named_is_the_one_that_was_refused():
    assert ALLOWED_CLOSES_WHEN.match(_line("mac/*state/pi-bridge-runs*"))


@pytest.mark.parametrize("cmd", [
    "true",
    "python3 other.py --row a",
    "python3 science/datamap.py --row a; rm -rf /",
    "python3 science/datamap.py --row ../../etc",
    "python3 science/datamap.py --row mac/../etc",
    "python3 science/datamap.py --row a && curl http://x",
    "python3 science/datamap.py --row $(whoami)",
    "python3 science/datamap.py --row a b",
    "python3 science/datamap.py --row a\nrm -rf /",
    "python3 science/datamap.py --row mac/data\n",  # `$` would accept this; `\Z` does not
])
def test_a_shell_metacharacter_or_a_parent_directory_is_still_refused(cmd):
    assert not ALLOWED_CLOSES_WHEN.match(cmd), cmd


def test_an_over_long_row_line_is_refused_even_though_it_spells_a_key():
    long_key = "mac/" + ("a" * MAX_CLOSES_WHEN)
    assert ALLOWED_CLOSES_WHEN.match(_line(long_key)), "grammar alone would accept it"
    ran = []
    r = close_pass([{"number": 1, "body": f"Closes-when: `{_line(long_key)}`"}],
                   now=0.0, seen={}, cwd=".", post=False,
                   run=lambda c, w: ran.append(c) or (0, ""))
    assert r["refused"] == 1 and r["closed"] == [] and ran == []


def test_a_refused_line_is_counted_and_never_run():
    ran = []
    r = close_pass([{"number": 1, "body": "Closes-when: `python3 science/datamap.py --row a; rm -rf /`"}],
                   now=0.0, seen={}, cwd=".", post=False,
                   run=lambda c, w: ran.append(c) or (0, ""))
    assert r["refused"] == 1 and ran == [], "a refused line must never reach the runner"
    assert r["closed"] == []


def test_a_real_row_key_now_runs_and_closes_on_exit_zero():
    ran = []
    key = "mac/*state/pi-bridge-runs*"
    r = close_pass([{"number": 533, "body": f"Closes-when: `{_line(key)}`"}],
                   now=0.0, seen={}, cwd=".", post=False,
                   run=lambda c, w: ran.append(c) or (0, "row closed"))
    assert ran == [_line(key)], "the board never ran the row it was told to run"
    assert r["closed"] == [(533, "closes-when")] and r["refused"] == 0


def test_a_real_row_key_that_exits_non_zero_is_held_not_closed():
    r = close_pass([{"number": 533, "body": f"Closes-when: `{_line('act/agent_decisions')}`"}],
                   now=0.0, seen={}, cwd=".", post=False, run=lambda c, w: (1, "still open"))
    assert r["closed"] == [] and r["held"] == 1


def test_the_frozen_key_set_still_matches_the_live_registry():
    if not os.path.exists(LIVE_VERDICTS):
        pytest.skip(f"no registry at {LIVE_VERDICTS}; the frozen sweep above still ran")
    with open(LIVE_VERDICTS, encoding="utf-8") as fh:
        keys = [e["key"] for e in json.load(fh)["entries"]]
    refused = [k for k in keys if not ALLOWED_CLOSES_WHEN.match(_line(k))]
    assert refused == [], f"live registry rows the board cannot run: {refused[:5]}"
