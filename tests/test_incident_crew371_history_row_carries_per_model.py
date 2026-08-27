"""Incident crew#371: the spend history row dropped by_model, so calls and cost per
model were computed on every run and never kept. The row now carries by_model and
reqs_by_model; scan() counts requests per model."""
import importlib.util, json, os, sys, pathlib

HERE = pathlib.Path(__file__).resolve().parents[1] / "estate"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_scan_empty_result_names_reqs_by_model(monkeypatch, tmp_path):
    spend = _load("estate_spend")
    monkeypatch.setattr(spend, "PROJECTS", str(tmp_path / "absent"))
    res = spend.scan(day="2026-08-28")
    assert res["reqs_by_model"] == {} and "by_model" in res


def test_record_writes_by_model_and_reqs_by_model(monkeypatch, tmp_path):
    sen = _load("estate_cost_sentinel")
    hist = tmp_path / "h.jsonl"
    monkeypatch.setattr(sen, "HISTORY", str(hist))
    monkeypatch.setattr(sen, "implausible", lambda res, now: None)
    sen.record({"day": "2026-08-28", "total": 1.5, "requests": 3, "by_owner": {"x": 1.5},
                "reqs_by_owner": {"x": 3}, "by_model": {"fable-5": 1.5},
                "reqs_by_model": {"fable-5": 3}})
    row = json.loads(hist.read_text().splitlines()[-1])
    assert row["by_model"] == {"fable-5": 1.5} and row["reqs_by_model"] == {"fable-5": 3}


def test_record_without_per_model_still_writes_empty_maps(monkeypatch, tmp_path):
    # An older scan() result must not crash the writer: the row carries {} not a KeyError.
    sen = _load("estate_cost_sentinel")
    hist = tmp_path / "h.jsonl"
    monkeypatch.setattr(sen, "HISTORY", str(hist))
    monkeypatch.setattr(sen, "implausible", lambda res, now: None)
    sen.record({"day": "2026-08-28", "total": 0.1, "requests": 1, "by_owner": {}})
    row = json.loads(hist.read_text().splitlines()[-1])
    assert row["by_model"] == {} and row["reqs_by_model"] == {}
