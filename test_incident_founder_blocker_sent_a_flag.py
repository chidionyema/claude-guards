"""Incident 2026-08-26: `founder-blocker.py --help` reached Telegram as "STAGED: --help is ready"
(msg 14081) and a second check sent "STAGED: check" (14083). Class: a CLI that messages the founder
treats any unrecognised flag as message text. Rung 4. Both ways: a flag exits 2 before send(); a
real action still parses. No test here ever calls send().
"""
import importlib.machinery
import importlib.util
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    loader = importlib.machinery.SourceFileLoader("founder_blocker", str(HERE / "founder-blocker.py"))
    spec = importlib.util.spec_from_loader("founder_blocker", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_incident_founder_blocker_sent_a_flag(monkeypatch):
    fb = _load()
    monkeypatch.setattr(fb, "send", lambda *a, **k: pytest.fail("send() must not run"))
    for argv in (["--help"], ["-h"], ["--staged", "5", "--bogus"], ["--unknown=1", "action"]):
        with pytest.raises(SystemExit) as e:
            fb.parse_argv(argv)
        assert e.value.code == 2, argv
    assert fb.parse_argv(["Raise the node pool", "--staged", "30", "--session", "abc"]) == (
        ["Raise the node pool"], "abc", 30, False, None)
    assert fb.parse_argv(["Tap the YubiKey", "--physical"]) == (["Tap the YubiKey"], "", None, True, None)
