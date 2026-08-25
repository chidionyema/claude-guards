"""Incident 2026-08-26 (crew#269): founder-blocker.py sent the catalogue password over Telegram.
Rung 4. The guard refuses credential-shaped text and permits an ordinary blocker, in one run.
"""
import importlib.machinery
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    loader = importlib.machinery.SourceFileLoader("founder_blocker", str(HERE / "founder-blocker.py"))
    spec = importlib.util.spec_from_loader("founder_blocker", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_incident_founder_blocker_pushed_a_password():
    fb = _load()
    refused = [
        "Catalogue is live: https://x.example — Username: founder  Password: RKm0p9WE7oX (reply SEEN)",
        "set TELEGRAM token=notarealvalue12",
        "api_key = notarealvalue34",
        "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nabc",  # built in two parts so the push gate sees no key block
    ]
    permitted = [
        "Backstage catalogue is live: https://catalogue.example — sign in with GitHub. Reply SEEN.",
        "GitHub Actions billing is failing; fix the payment method at https://github.com/settings/billing then reply PAID.",
        "The password reset link is on the login page; no value is in this message.",
    ]
    assert all(fb.carries_credential(t) for t in refused), [t for t in refused if not fb.carries_credential(t)]
    assert not any(fb.carries_credential(t) for t in permitted), [t for t in permitted if fb.carries_credential(t)]
