"""Incident crew#306: launchd ran auto-objective --scan with PATH=/usr/bin:/bin and printed
BLIND every 5 minutes because gh lives in /usr/local/bin. Rung 4. Both ways."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import estate_board  # noqa: E402


def test_gh_resolves_without_path(monkeypatch, tmp_path):
    fake = tmp_path / "gh"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(estate_board, "_GH_DIRS", (str(tmp_path),))
    assert estate_board.gh_bin() == str(fake)


def test_gh_missing_everywhere_falls_back_to_name(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(estate_board, "_GH_DIRS", (str(tmp_path / "nowhere"),))
    assert estate_board.gh_bin() == "gh"


def test_gh_on_path_wins(monkeypatch, tmp_path):
    fake = tmp_path / "gh"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(estate_board, "_GH_DIRS", ())
    assert estate_board.gh_bin() == str(fake)
