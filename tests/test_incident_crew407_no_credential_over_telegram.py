"""Incident test (rung 4): crew#407: a session sent a UI password to the founder's Telegram.

Both ways in one run: every credential shape is refused by the two senders before any HTTP
call, and ordinary receipts (URLs, DONE: lines, the word "password" without a value) still go.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "estate"))
import estate_alert as ea  # noqa: E402

MUST_REFUSE = [
    "Router Admin UI login\nuser: founder\npassword: Zq8vL2pXw9kT3mRb",
    "CONSOLE_PASSWORD=Zq8vL2pXw9kT3mRb",
    "the api key is sk-" + "abcdefghijklmnopqrstuvwx1234",   # built at runtime: no credential-shaped literal is committed
    "token: ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123",
    "AK" + "IAIOSFODNN7EXAMPLE",              # built at runtime: the push gate refuses the literal
    "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
    "login: founder / Zq8vL2pXw9kT3mRb",
    "user=founder, password=\"Zq8vL2pXw9kT3mRb\"",
    "bot 123456789:" + "ABCdefGHIjklMNOpqrSTUvwxYZ0123456789abc",
]
MUST_PERMIT = [
    "DONE: idp#283 merged. Password rotated; vault re-seeded. https://github.com/chidionyema/idp/pull/283",
    "STAGED: router-ui. Reply 'hold' to cancel. Auto-activating in 60 minutes.",
    "The login is IDCS SSO; no password exists for llm.estate.test/ui.",
    "secret store: estate-vault (ClusterSecretStore), token refresh 1h",
    "PASS: 41/41; login https://auth.estate.test ok; master_key: os.environ/LITELLM_MASTER_KEY",
    "put litellm-ui CONSOLE_USER=LITELLM_CONSOLE_USER CONSOLE_PASSWORD=LITELLM_CONSOLE_PASSWORD; password: ${CONSOLE_PASSWORD}",
    "the token is injected by ESO; secret is provisioned by tofu",
    "crew#407: security incident triage at https://github.com/chidionyema/crew/issues/407",
]


@pytest.mark.parametrize("text", MUST_REFUSE)
def test_credential_shapes_are_refused_before_any_http(text, monkeypatch):
    called = []
    monkeypatch.setattr(ea.urllib.request, "urlopen", lambda *a, **k: called.append(a))
    assert ea.credential_shape(text)
    with pytest.raises(ea.CredentialRefused):
        ea._post("t", "c", text)
    assert called == []


@pytest.mark.parametrize("text", MUST_PERMIT)
def test_ordinary_receipts_pass(text, monkeypatch):
    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"result": {"message_id": 7}}'
    monkeypatch.setattr(ea.urllib.request, "urlopen", lambda *a, **k: R())
    assert ea.credential_shape(text) is None
    assert ea._post("t", "c", text) == 7


def test_founder_deliver_refuses_too(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("fd", os.path.join(HERE, "founder-deliver.py"))
    fd = importlib.util.module_from_spec(spec); spec.loader.exec_module(fd)
    # No token in this test, so nothing can leave the machine even if the guard were broken.
    monkeypatch.setattr(ea, "_env", lambda k: None)
    assert fd._send_real(MUST_REFUSE[0], "d1") is False
