"""基线冻结与 diff 测试。"""
from __future__ import annotations

import json

import pytest

from core.types import Prediction, RunResult, SampleMetrics
from runner.aggregate import engine_summary, percentile, summarize_run
from runner.baseline import (
    compare,
    diff_report,
    freeze,
    load_baseline,
    resolve_baseline,
)


def make_run(
    name: str,
    cers: dict[str, float],
    engine: str = "e1",
    latency_ms: float = 10.0,
    cost_usd: float = 0.1,
) -> RunResult:
    preds: list[Prediction] = []
    metrics: list[SampleMetrics] = []
    for sid, cer in cers.items():
        preds.append(Prediction(
            engine_id=engine, sample_id=sid, task="recognize",
            latency_ms=latency_ms, cost_usd=cost_usd,
        ))
        metrics.append(SampleMetrics(
            sample_id=sid, cer=cer, char_recall=1 - cer, line_f1=max(0.0, 1 - cer),
            latency_ms=latency_ms, cost_usd=cost_usd,
        ))
    return RunResult(
        run_name=name, config={}, samples=list(cers),
        predictions=preds, metrics=metrics,
        created_at="2024-01-01T00:00:00+00:00",
    )


def test_percentile() -> None:
    assert percentile([], 0.5) is None
    assert percentile([5.0], 0.9) == 5.0
    assert percentile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert percentile([1.0, 2.0], 0.5) == pytest.approx(1.5)
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.99) == pytest.approx(3.97)


def test_engine_summary_skips_none_and_cache_hits() -> None:
    metrics = [
        SampleMetrics(sample_id="a", cer=0.2, latency_ms=10.0, cost_usd=0.1),
        SampleMetrics(sample_id="b", cer=0.4, latency_ms=20.0, cost_usd=0.1),
        SampleMetrics(sample_id="c", cer=None, latency_ms=0.0, cost_usd=0.0),
    ]
    summary = engine_summary(metrics, [False, False, True])
    assert summary["samples_total"] == 3
    assert summary["samples_ok"] == 3
    assert summary["cache_hits"] == 1
    assert summary["metrics"]["cer"] == pytest.approx(0.3)  # None 不参与均值
    assert summary["latency_ms"]["p50"] == pytest.approx(15.0)  # 缓存命中不计延迟
    assert summary["cost"]["per_1000"] == pytest.approx(100.0)


def test_summarize_run_requires_aligned_lists() -> None:
    run = make_run("r", {"a": 0.1})
    run.metrics.pop()
    with pytest.raises(ValueError, match="predictions 与 metrics"):
        summarize_run(run)


def test_freeze_and_load(tmp_path) -> None:
    run = make_run("r1", {"a": 0.5, "b": 0.2})
    path = freeze(run, tmp_path / "baseline.json", source="results/r1/run.json")
    payload = load_baseline(path)
    assert payload["run_name"] == "r1"
    assert payload["source"] == "results/r1/run.json"
    assert payload["engines"]["e1"]["samples"]["a"]["cer"] == 0.5
    assert payload["engines"]["e1"]["metrics"]["cer"] == pytest.approx(0.35)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_resolve_baseline_by_name(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results" / "baselines").mkdir(parents=True)
    target = tmp_path / "results" / "baselines" / "r1.json"
    target.write_text("{}", encoding="utf-8")
    assert resolve_baseline("r1").resolve() == target
    with pytest.raises(FileNotFoundError):
        resolve_baseline("nope")


def test_compare_direction_and_sample_changes(tmp_path) -> None:
    old = make_run("old", {"a": 0.5, "b": 0.2})
    baseline = json.loads(
        freeze(old, tmp_path / "b.json").read_text(encoding="utf-8")
    )
    new = make_run("new", {"a": 0.3, "b": 0.2, "c": 0.1})
    rows, samples = compare(new, baseline)

    cer_rows = {r.engine_id: r for r in rows if r.metric == "cer"}
    assert cer_rows["e1"].verdict == "变好"
    # 基线均值 (0.5+0.2)/2=0.35，当前 (0.3+0.2+0.1)/3=0.20
    assert cer_rows["e1"].delta == pytest.approx(-0.15)

    recall_rows = [r for r in rows if r.metric == "char_recall"]
    assert all(r.verdict == "变好" for r in recall_rows)

    sample_by_id = {s.sample_id: s for s in samples}
    assert sample_by_id["a"].verdict == "变好"
    assert sample_by_id["b"].verdict == "持平"
    assert sample_by_id["c"].verdict == "缺失"


def test_compare_detects_regression_and_new_engine(tmp_path) -> None:
    baseline = json.loads(
        freeze(make_run("old", {"a": 0.1}), tmp_path / "b.json").read_text(encoding="utf-8")
    )
    current = make_run("new", {"a": 0.3})
    current.predictions.append(
        Prediction(engine_id="e2", sample_id="a", task="recognize")
    )
    current.metrics.append(SampleMetrics(sample_id="a", cer=0.05))

    report = diff_report(current, baseline)
    cer_rows = [r for r in report["metric_rows"] if r["metric"] == "cer"]
    by_engine = {r["engine_id"]: r for r in cer_rows}
    assert by_engine["e1"]["verdict"] == "变坏"
    assert by_engine["e2"]["baseline"] is None
    assert by_engine["e2"]["verdict"] == "缺失"
    assert report["sample_changes"]["counts"]["变坏"] == 1
    assert report["sample_set_changed"] is True
