"""Incident 2026-09-01: four secret-scrub copies ran side by side (one per session's Stop
hook), 70-90 % CPU each, load 41-88 on the founder's 16 GB Mac. A second copy exits at once."""

from __future__ import annotations

import fcntl
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_SCRUB_LOCK", str(tmp_path / "scrub.lock"))
    monkeypatch.setenv("SECRET_SCRUB_OFFSETS", str(tmp_path / "offsets.json"))
    spec = importlib.util.spec_from_file_location(
        "secret_scrub", HERE / "secret-scrub.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_second_copy_leaves_at_once(monkeypatch, tmp_path, capsys):
    mod = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "targets", lambda: [])
    holder = (tmp_path / "scrub.lock").open("a+")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert mod.run(check_only=True) == 0
        assert "another copy is already scanning" in capsys.readouterr().out
    finally:
        holder.close()


def test_a_free_lock_lets_the_scan_run(monkeypatch, tmp_path, capsys):
    mod = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "targets", lambda: [])
    assert mod.run(check_only=True) == 0
    assert "another copy" not in capsys.readouterr().out
