"""Incident 2026-08-26 (crew#269 -> crew#281): a session sent the founder a FOUNDER ACTION to create a
GitHub OAuth App in a browser console. Founder: "Do not ask the founder to use the GitHub UI ...
The phrase FOUNDER ACTION: is now heavily restricted." Rung 4. The class: a founder step that a
token or an API could take, announced as his to click. Proved both ways in one run across the
three guards that see a founder-facing line.
"""
import importlib.machinery
import importlib.util
import pathlib
import time

HERE = pathlib.Path(__file__).resolve().parent


def _load(name, fname):
    loader = importlib.machinery.SourceFileLoader(name, str(HERE / fname))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_founder_blocker_refuses_a_console_step_and_permits_a_device_step():
    fb = _load("founder_blocker", "founder-blocker.py")
    console = [
        "create the OAuth App at https://github.com/settings/applications/new and paste the id into the vault",
        "add Account -> Zero Trust: Edit to the Cloudflare token in the dashboard",
        "approve the billing page at https://github.com/settings/billing",
    ]
    physical = [
        "plug the hardware key into the laptop and touch it when it blinks",
        "open the authenticator on your phone and approve the sign-in",
        "power the Mac mini back on; it is off at the plug",
    ]
    assert not any(fb.names_physical(t) for t in console), [t for t in console if fb.names_physical(t)]
    assert all(fb.names_physical(t) for t in physical), [t for t in physical if not fb.names_physical(t)]
    # the refusal path needs no Telegram: it returns 0 before any send
    assert fb.send(console[0], physical=True) == 0
    assert fb.staged_text("platform/access apply (idp#150)", 60) == (
        "STAGED: platform/access apply (idp#150) is ready. Reply 'go' to execute immediately, "
        "'hold' to review. Auto-activating in 60 minutes.")


def test_blocker_guard_grades_the_ledger_row_kind():
    bg = _load("blocker_guard", "blocker-guard.py")
    now = time.time()
    staged = [{"source": "founder-blocker", "outcome": "staged", "key": "staged:60:x", "msg_id": 7, "ts": now}]
    physical = [{"source": "founder-blocker", "outcome": "sent", "key": "physical:x", "msg_id": 8, "ts": now}]
    legacy = [{"source": "founder-blocker", "outcome": "sent", "key": "create the OAuth App", "msg_id": 9, "ts": now}]
    assert bg.verdict("STAGED: x is ready. Reply 'go' ...", staged, now)[0] == 0
    assert bg.verdict("STAGED: x is ready.", [], now)[0] == 2
    assert bg.verdict("FOUNDER ACTION: touch the hardware key", physical, now)[0] == 0
    assert bg.verdict("FOUNDER ACTION: create the OAuth App", legacy, now)[0] == 2   # the incident shape
    assert bg.verdict("FOUNDER ACTION: create the OAuth App", staged, now)[0] == 2
    assert bg.verdict("INVENTORY: nothing founder-facing", [], now)[0] == 0
    assert bg.verdict("FOUNDER ACTION: x", None, now)[0] == 0   # BLIND permits and says so


def test_dod_guard_accepts_the_staged_shape_and_refuses_a_loose_one():
    dod = _load("dod_guard", "dod-guard.py")
    good = ("STAGED: platform/access apply (idp#150) is ready. Reply 'go' to execute immediately, "
            "'hold' to review. Auto-activating in 60 minutes.\n")
    assert dod.offences(good) == []
    assert dod.offences("STAGED: platform/access apply is ready, say go.\n")
    assert dod.offences("STAGED: x is ready. Reply 'go' to execute immediately, 'hold' to review. Auto-activating soon.\n")
