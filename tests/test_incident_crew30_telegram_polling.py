"""Incident test (rung 4), crew#30: Telegram polling conflicts were never counted.

Executes the scenario in features/hard_execution_chain.feature against
estate_audit.c_telegram_polling with a fixture gateway.log: 0 lines -> ok,
25 lines in the last 24 h -> critical, no log -> unknown.
"""
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _audit():
    spec = importlib.util.spec_from_file_location("estate_audit", os.path.join(HERE, "estate", "estate_audit.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["estate_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


def _sev(mod, home):
    os.environ["HERMES_V2_HOME"] = str(home)
    (r,) = mod.c_telegram_polling()
    return r["severity"], r["value"]


def test_incident_crew30_telegram_polling(tmp_path):
    mod = _audit()
    assert _sev(mod, tmp_path) == (mod.UNK, "NO LOG")
    log = tmp_path / "logs" / "gateway.log"
    log.parent.mkdir()
    now = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    old = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 3 * 86400))
    log.write_text(f"{old} Telegram polling conflict (stale, must not count)\n" * 30)
    assert _sev(mod, tmp_path) == (mod.OK, "0")
    with open(log, "a") as fh:
        fh.write(f"{now} Telegram polling conflict\n" * 25)
    assert _sev(mod, tmp_path) == (mod.CRIT, "25")
