"""Incident 2026-08-27 (crew#284): three FOUNDER ACTION lines asked the founder to resend /sb-list
while every send already sat in the gateway's state.db as a user row; the session could have replayed
it. His words: "how many times do I need to send /sb-list, this is major friction", "do your own
testing". Class: asking the founder to reproduce an input the machine already holds. Rung 4.
Both ways in one run: a resend of a command state.db holds is refused before any send; a resend
of a command he never sent, and an action that is not a resend, still pass. No test calls Telegram.
"""
import importlib.machinery
import importlib.util
import pathlib
import sqlite3

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    loader = importlib.machinery.SourceFileLoader("founder_blocker", str(HERE / "founder-blocker.py"))
    spec = importlib.util.spec_from_loader("founder_blocker", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _db(tmp_path):
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("create table messages (id integer primary key, role text, content text)")
    con.execute("insert into messages values (10297, 'user', '/sb-list')")
    con.commit(); con.close()
    return db


def test_incident_crew284_founder_asked_to_resend(tmp_path, monkeypatch):
    fb = _load()
    db = _db(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # must refuse: he already sent it
    held = fb.already_on_disk("On your phone, in Telegram: send /sb-list to Otto once more", db)
    assert held == "/sb-list is state.db row 10297"
    assert fb.already_on_disk("resend `/sb-list` please") == held  # path from HERMES_HOME (LAW 46)
    # must pass: never sent, or not a resend at all
    assert fb.already_on_disk("send /sb-show 1 to Otto", db) is None
    assert fb.already_on_disk("tap the YubiKey when it blinks", db) is None
    # send() refuses before any network call
    monkeypatch.setattr(fb.telegram_ledger, "record", lambda *a, **k: None)
    monkeypatch.setattr(fb.ea, "_env", lambda k: (_ for _ in ()).throw(AssertionError("must refuse before env")))
    assert fb.send("send /sb-list to Otto again", physical=True) == 0


def test_incident_crew284_no_state_db_is_not_a_verdict(tmp_path, monkeypatch):
    fb = _load()
    monkeypatch.delenv("HERMES_HOME", raising=False)
    assert fb.already_on_disk("send /sb-list to Otto") is None
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))  # no state.db there
    assert fb.already_on_disk("send /sb-list to Otto") is None
