# retired/ — what to know

- A script lands here when the `RETIRED` dict in `test_incident_crew69_every_script_is_wired.py` names it with a reason and nothing on the machine calls it. The test fails if a name is listed but the file is still at the top level, or listed but not under `retired/`.
- To bring one back: `git mv retired/<name> <name>`, delete its `RETIRED` line, and wire it (hook, launchd, PATH or a caller); the test tells you which state it landed in.
- To turn this off: there is nothing to turn off; the directory is inert. Deleting a retired file only needs its `RETIRED` line removed.
