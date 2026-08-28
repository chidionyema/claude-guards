"""2026-08-28 00:57Z: `ln -sf X X` unlinked crew/science/warehouse.db (97 MB) and left a
symlink to its own path. rule_self_symlink refuses the self-link and `-sf` over an
existing regular file; a link into another directory and a marked command pass."""
import importlib.machinery, importlib.util, os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("rule_guard", str(HERE / "rule-guard.py"))
spec = importlib.util.spec_from_loader("rule_guard", loader)
assert spec is not None
rg = importlib.util.module_from_spec(spec)
sys.modules["rule_guard"] = rg
loader.exec_module(rg)


def test_self_link_is_refused(tmp_path):
    f = tmp_path / "w.db"; f.write_bytes(b"x")
    assert rg.rule_self_symlink(f"ln -sf {f} {f}")
    assert rg.rule_self_symlink(f"cd {tmp_path} && ln -sf {f} w.db")
    assert rg.rule_self_symlink(f"cd {tmp_path} && ln -sf {f} .")  # dir form resolves to the same name


def test_force_over_regular_file_is_refused(tmp_path):
    f = tmp_path / "w.db"; f.write_bytes(b"x")
    other = tmp_path / "other.db"; other.write_bytes(b"y")
    assert rg.rule_self_symlink(f"ln -sf {other} {f}")
    assert rg.rule_self_symlink(f"ln -s {other} {f}") is None  # no -f: ln itself refuses, nothing lost


def test_link_elsewhere_and_marker_pass(tmp_path):
    f = tmp_path / "w.db"; f.write_bytes(b"x")
    d = tmp_path / "wt"; d.mkdir()
    assert rg.rule_self_symlink(f"ln -s {f} {d}/w.db") is None
    assert rg.rule_self_symlink(f"ln -sf {f} {f}  # symlink-intended") is None
    assert rg.rule_self_symlink(f"cp {f} {f}.bak") is None
