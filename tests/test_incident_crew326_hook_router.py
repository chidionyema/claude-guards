"""Incident test (rung 4), crew#326: the shared git hook router was overwritten with a
refuse-all stub and every commit and push on the machine was refused, with nothing red.

Executes the scenario in features/hard_execution_chain.feature: estate_audit.c_hook_router
is ok when router-selftest passes, critical when it fails, unknown when it is missing.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _audit():
    spec = importlib.util.spec_from_file_location("estate_audit", os.path.join(HERE, "estate", "estate_audit.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["estate_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


def _sev(mod, home):
    os.environ["ESTATE_HOME"] = str(home)
    (r,) = mod.c_hook_router()
    return r["severity"]


def test_incident_crew326_hook_router(tmp_path):
    mod = _audit()
    assert _sev(mod, tmp_path) == mod.UNK
    st = tmp_path / "guards" / "bin" / "router-selftest"
    st.parent.mkdir(parents=True)
    st.write_text("#!/bin/sh\necho 'ok router-selftest'\nexit 0\n"); st.chmod(0o755)
    assert _sev(mod, tmp_path) == mod.OK
    st.write_text("#!/bin/sh\necho 'FAIL router-selftest'\nexit 1\n")
    assert _sev(mod, tmp_path) == mod.CRIT
