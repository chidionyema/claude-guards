"""Founder, 2026-09-09: "every founder action should come with clear instructions, else needs back and forth".

Incident: a FOUNDER ACTION told him to "create the Linear OAuth app for Cyrus from your phone using
Telegram pin 47292" and named no page, no button, no callback URL and no vault field. He had to ask.
The class: a physical hand-back with no steps. Refused at the one send path; steps ride with the action.
"""

import importlib.util, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location(
    "founder_blocker", HERE / "founder-blocker.py"
)
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)


def test_physical_without_steps_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(fb.telegram_ledger, "record", lambda *a, **k: None)
    monkeypatch.setattr(fb, "register_rows", lambda: [])
    assert fb.send("plug the phone in", "word", physical=True, register="none") == 0
    assert "--steps" in capsys.readouterr().err


def test_one_step_is_not_instructions(monkeypatch):
    monkeypatch.setattr(fb.telegram_ledger, "record", lambda *a, **k: None)
    monkeypatch.setattr(fb, "register_rows", lambda: [])
    assert (
        fb.send(
            "plug the phone in",
            "word",
            physical=True,
            register="none",
            steps="open the app",
        )
        == 0
    )


def test_steps_ride_with_the_action(monkeypatch):
    monkeypatch.setattr(fb.telegram_ledger, "record", lambda *a, **k: None)
    monkeypatch.setattr(fb, "register_rows", lambda: [])
    monkeypatch.setattr(fb.ea, "_env", lambda k: "x")
    sent = {}

    def fake_api(tok, method, **p):
        sent.setdefault(method, p)
        return {"result": {"message_id": 7}}

    monkeypatch.setattr(fb, "_api", fake_api)
    mid = fb.send(
        "plug the phone in",
        "word",
        physical=True,
        register="none",
        steps="Open Linear on the phone|Tap Settings, API, OAuth applications|Copy the client id into Bitwarden item cyrus-linear, field client_id",
    )
    assert mid == 7
    text = sent["sendMessage"]["text"]
    assert text.startswith("FOUNDER ACTION: plug the phone in")
    assert "Steps:\n1. Open Linear on the phone.\n2. Tap Settings" in text
    assert "3. Copy the client id" in text


def test_parse_argv_reads_steps():
    args, _, _, physical, register, steps = fb.parse_argv(
        ["do it", "word", "--physical", "--register", "none", "--steps", "a|b"]
    )
    assert (
        args == ["do it", "word"] and physical and register == "none" and steps == "a|b"
    )
