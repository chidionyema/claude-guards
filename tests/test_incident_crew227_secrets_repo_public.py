"""Incident test (rung 4), crew#227: estate-secrets, a sops ciphertext repo, was PUBLIC on 2026-08-27
and nothing off the laptop noticed. Both ways in one run, no network: a repo a stranger gets 200
for is PUBLIC; one they get 404 for is private; an unreachable API is BLIND, never a verdict.
"""
import importlib.util
import io
import os
import urllib.error

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    spec = importlib.util.spec_from_file_location(
        "rmbp", os.path.join(HERE, "estate", "repo_must_be_private.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener_for(codes):
    def opener(req, timeout=0):
        repo = req.full_url.split("/repos/")[1]
        code = codes[repo]
        if code is None:
            raise urllib.error.URLError("no route")
        if code == 200:
            return _Resp(b"{}")
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
    return opener


def test_incident_crew227_public_ciphertext_repo_is_named_and_private_one_is_not():
    m = _mod()
    rows = m.verdicts(("o/leaked", "o/hidden", "o/unreachable"),
                      opener=_opener_for({"o/leaked": 200, "o/hidden": 404, "o/unreachable": None}))
    assert dict((r, v) for r, _, v in rows) == {
        "o/leaked": "PUBLIC", "o/hidden": "private", "o/unreachable": "BLIND"}


def test_estate_secrets_is_on_the_list():
    assert "chidionyema/estate-secrets" in _mod().MUST_BE_PRIVATE
