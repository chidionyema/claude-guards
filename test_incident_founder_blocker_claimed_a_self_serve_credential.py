"""Incident 2026-08-26 (crew#325, crew#267, crew#284): four sessions sent FOUNDER ACTION: "tap Create on
the estate-agents GitHub App" while a deploy key any session can mint did the same job; a day was
lost. Founder: "we have lost a whole day because of this ... everyone claiming founder dependency".
Rung 4. The class: a founder step announced without checking the Capabilities register in
~/AGENTS.md. Proved both ways in one run: a named register row is refused with its self-serve
path; a missing flag is refused with the table; `none` passes to the physical check."""
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


TABLE = """# Capabilities register — read before writing `FOUNDER ACTION:`

| Need | Self-serve path | Since |
|------|-----------------|-------|
| Flux git writer credential (idp-writer) | deploy key via `gh api repos/chidionyema/idp/keys`, then `vault-seed.yml -f entry=flux-writer` | idp#248 |
| Any vault secret | `gh secret set SEED_<KEY>` then `gh workflow run vault-seed.yml` | idp#243 |
"""


def test_register_row_is_refused_and_none_passes_through(tmp_path, monkeypatch, capsys):
    fb = _load("founder_blocker", "founder-blocker.py")
    reg = tmp_path / "AGENTS.md"; reg.write_text(TABLE)
    monkeypatch.setattr(fb, "REGISTER", str(reg))
    monkeypatch.setattr(fb.telegram_ledger, "record", lambda *a, **k: None)
    rows = fb.register_rows(str(reg))
    assert [n for n, _ in rows] == ["Flux git writer credential (idp-writer)", "Any vault secret"]
    assert fb.register_match("flux git writer credential", rows)[1].startswith("deploy key")
    assert fb.register_match("GitHub App", rows) is None

    physical = "tap the hardware key when it blinks to approve the GitHub App"
    assert fb.send(physical, physical=True, register="Flux git writer credential (idp-writer)") == 0
    assert "self-serve path exists" in capsys.readouterr().err
    assert fb.send(physical, physical=True) == 0
    err = capsys.readouterr().err
    assert "needs --register" in err and "Any vault secret" in err
    # `none` clears the register gate; the next gate (Telegram env) is what stops it here
    monkeypatch.setattr(fb.ea, "_env", lambda k: "")
    assert fb.send(physical, physical=True, register="none") == 0
    assert capsys.readouterr().err.startswith("BLIND: TELEGRAM")


def test_live_register_holds_the_deploy_key_row():
    fb = _load("founder_blocker", "founder-blocker.py")
    rows = fb.register_rows()
    assert fb.register_match("Flux git writer credential", rows), rows
