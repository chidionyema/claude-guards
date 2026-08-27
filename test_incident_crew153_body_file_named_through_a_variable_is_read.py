"""Incident crew#153 (2026-08-27): `gh pr create --body-file "$SP/body.md"` was refused by
dupe-work-fence as "does not exist" for a file that existed, because the path was checked
literally; the shell would have expanded $SP. Rule: the fence expands $VAR and ~ from its own
environment before it looks for the file (a guard that refuses correct work is an outage, LAW 38).
Both ways: a variable the hook can see is expanded and the body is read; a path the hook still
cannot resolve is refused with the same "does not exist" line as before, so nothing is silenced."""
import contextlib
import importlib.util
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _fence():
    spec = importlib.util.spec_from_file_location("dwf", os.path.join(HERE, "dupe-work-fence.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, argv, claims):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = mod.check(argv, os.getcwd(), claims_fn=lambda _cwd: claims)
    return rc, err.getvalue()


def test_body_file_named_through_a_variable_is_expanded_and_read(tmp_path, monkeypatch):
    (tmp_path / "body.md").write_text("Closes #404\n", encoding="utf-8")
    monkeypatch.setenv("DWF_TEST_SP", str(tmp_path))
    mod = _fence()
    argv = ["gh", "pr", "create", "--title", "fix: x", "--body-file", "$DWF_TEST_SP/body.md"]
    rc, err = _run(mod, argv, {404: [409]})
    assert rc == 2, err
    assert "already" in err and "does not exist" not in err, err


def test_tilde_is_expanded(tmp_path, monkeypatch):
    (tmp_path / "body.md").write_text("Closes #404\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    mod = _fence()
    rc, err = _run(mod, ["gh", "pr", "create", "--body-file", "~/body.md"], {404: [409]})
    assert rc == 2 and "already" in err, err


def test_a_path_the_hook_cannot_resolve_is_still_refused_as_missing(monkeypatch):
    monkeypatch.delenv("DWF_UNSET_IN_HOOK", raising=False)
    mod = _fence()
    argv = ["gh", "pr", "create", "--body-file", "$DWF_UNSET_IN_HOOK/body.md"]
    rc, err = _run(mod, argv, {})
    assert rc == 2 and "does not exist" in err, err
