"""Incident 2026-08-26 (idp#160, Telegram msg 14076): a session passed the whole STAGED
template as the action, and the channel read "STAGED: STAGED: ... Auto-activating in 60
minutes is ready. Reply 'go' ... Auto-activating in 60 minutes." Rung 4. The class: a
caller composing the sentence that founder-blocker owns. Proved both ways in one run: a
pasted template and a bare action phrase produce the same single sentence, and a plain
action is not altered.
"""
import importlib.machinery
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def _load(name, fname):
    loader = importlib.machinery.SourceFileLoader(name, str(HERE / fname))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_staged_text_is_composed_once_whatever_the_caller_pastes():
    fb = _load("founder_blocker", "founder-blocker.py")
    pasted = ("STAGED: grow the OKE A1 node to 4 OCPU / 24 GB (idp#160). Reply 'APPROVE: scale' "
              "to execute now, 'hold' to cancel. Auto-activating in 60 minutes.")
    bare = "grow the OKE A1 node to 4 OCPU / 24 GB (idp#160)"
    assert fb.staged_text(pasted, 60) == fb.staged_text(bare, 60)
    out = fb.staged_text(pasted, 60)
    assert out.count("STAGED:") == 1 and out.count("Auto-activating") == 1 and out.count("is ready") == 1
    # the good case: a plain action keeps its words, only a trailing full stop goes
    assert fb.normalise_action("run bin/idp-oci-bootstrap in your session.") == "run bin/idp-oci-bootstrap in your session"
    assert fb.normalise_action("FOUNDER ACTION: tap the YubiKey") == "tap the YubiKey"
