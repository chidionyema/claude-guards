#!/bin/sh
# Verify command for this repo. Resolved by hermes-agent's detect_project_facts
# (scripts/run_tests.sh is its first-priority marker), so the verification
# ledger and the claim gate can back a DONE with a green run here.
# Only the two hermetic pytest files run. The other three test files are
# self-running scripts that execute at import and call sys.exit, which makes
# bare `pytest` in this directory die with INTERNALERROR (measured 2026-08-24:
# test_bridge_edges.py:364, test_bridge_live.py:247, test_kimi_bridge_reap.py:90).
# test_bridge_live.py also touches the network, so it stays out of the gate.
cd "$(dirname "$0")/.." || exit 1
exec python3 -m pytest test_kimi_bridge_boot.py test_kimi_connect_parser.py -q "$@"
