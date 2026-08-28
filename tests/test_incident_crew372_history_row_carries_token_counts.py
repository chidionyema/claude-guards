"""Incident crew#372: act/context_waste was NEVER_EMITTED. The spend scan read every
call's cache_read_input_tokens for weeks and kept only the dollars. The history row now
carries token counts by driver and reread_pct, the share of tokens sent to the model that
were a cache read: context re-sent unchanged from the previous call."""
import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parents[1] / "estate"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _transcript(tmp_path, rows):
    proj = tmp_path / "-Users-x-dev-code"
    proj.mkdir()
    (proj / "s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return tmp_path


def test_scan_counts_tokens_by_driver(monkeypatch, tmp_path):
    spend = _load("estate_spend")
    root = _transcript(tmp_path, [
        {"timestamp": "2026-08-28T10:00:00Z", "message": {"id": "a", "model": "claude-fable-5",
         "usage": {"input_tokens": 10, "cache_read_input_tokens": 900,
                   "cache_creation": {"ephemeral_5m_input_tokens": 90}, "output_tokens": 5}}},
        {"timestamp": "2026-08-28T10:01:00Z", "message": {"id": "b", "model": "claude-fable-5",
         "usage": {"input_tokens": 0, "cache_read_input_tokens": 1000,
                   "cache_creation_input_tokens": 0, "output_tokens": 7}}},
    ])
    monkeypatch.setattr(spend, "PROJECTS", str(root))
    monkeypatch.setattr(spend, "_local_day", lambda ts: "2026-08-28")
    res = spend.scan(day="2026-08-28")
    assert res["tokens"] == {"raw_input": 10, "cache_read": 1900, "cache_write": 90, "output": 12}
    assert spend.reread_pct(res["tokens"]) == 95.0     # 1900 of 2000 sent


def test_reread_pct_is_none_not_zero_on_an_empty_day():
    spend = _load("estate_spend")
    assert spend.reread_pct({}) is None
    assert spend.reread_pct({"output": 40}) is None


def test_scan_empty_result_names_tokens(monkeypatch, tmp_path):
    spend = _load("estate_spend")
    monkeypatch.setattr(spend, "PROJECTS", str(tmp_path / "absent"))
    assert spend.scan(day="2026-08-28")["tokens"] == {}


def test_record_writes_tokens_and_reread_pct(monkeypatch, tmp_path):
    sen = _load("estate_cost_sentinel")
    hist = tmp_path / "h.jsonl"
    monkeypatch.setattr(sen, "HISTORY", str(hist))
    monkeypatch.setattr(sen, "implausible", lambda res, now: None)
    sen.record({"day": "2026-08-28", "total": 1.5, "requests": 3, "by_owner": {"x": 1.5},
                "tokens": {"raw_input": 100, "cache_read": 300, "cache_write": 100, "output": 9}})
    row = json.loads(hist.read_text().splitlines()[-1])
    assert row["tokens"]["cache_read"] == 300 and row["reread_pct"] == 60.0


def test_record_without_tokens_writes_empty_map_and_null_pct(monkeypatch, tmp_path):
    sen = _load("estate_cost_sentinel")
    hist = tmp_path / "h.jsonl"
    monkeypatch.setattr(sen, "HISTORY", str(hist))
    monkeypatch.setattr(sen, "implausible", lambda res, now: None)
    sen.record({"day": "2026-08-28", "total": 0.1, "requests": 1, "by_owner": {}})
    row = json.loads(hist.read_text().splitlines()[-1])
    assert row["tokens"] == {} and row["reread_pct"] is None
