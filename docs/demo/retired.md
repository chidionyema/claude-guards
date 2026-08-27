# retired/ — what you see

Nothing runs. `retired/` holds scripts that no hook, launchd job, PATH entry or other script reaches (crew#69 row 2). What you see is the wiring census staying green:

```
$ python3 -m pytest -q test_incident_crew69_every_script_is_wired.py
8 passed
```

and `ls ~/.claude/scripts/*.py *.sh` no longer listing consult-verify.sh, setup-kimi-bridge.sh, edge_test.py or batching-compliance.py.
