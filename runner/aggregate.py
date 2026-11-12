"""RunResult 聚合：按引擎汇总指标、延迟分位、成本。"""
from __future__ import annotations

import math
from typing import Iterable

from core.types import RunResult, SampleMetrics

# 均值口径：只对非 None 值求均值（缺 GT / 不适用的指标不参与）
METRIC_KEYS = (
    "cer", "sub_rate", "del_rate", "ins_rate", "char_recall",
    "line_precision", "line_recall", "line_f1", "box_iou_mean", "exact_match",
)
# 样本级基线与 diff 用到的关键指标
SAMPLE_KEYS = ("cer", "char_recall", "line_f1", "box_iou_mean")


def percentile(values: Iterable[float], q: float) -> float | None:
    """线性插值分位数，q ∈ [0, 1]。空序列返回 None。"""
    data = sorted(values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return data[lo]
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def mean(values: Iterable[float]) -> float | None:
    data = list(values)
    return sum(data) / len(data) if data else None


def sample_view(sm: SampleMetrics) -> dict[str, float | None]:
    """单样本关键指标快照（写入 baseline，用于样本级涨跌定位）。"""
    view: dict[str, float | None] = {k: getattr(sm, k) for k in SAMPLE_KEYS}
    view["error"] = 1.0 if sm.error else 0.0
    return view


def engine_summary(
    metrics: list[SampleMetrics],
    cache_hit_flags: list[bool] | None = None,
) -> dict:
    """对单个引擎的样本指标做汇总。

    cache_hit_flags 与 metrics 等长；缓存命中样本的延迟/成本记 0，
    不能混进效率统计，但指标照常计入。
    """
    flags = list(cache_hit_flags or [False] * len(metrics))
    if len(flags) != len(metrics):
        raise ValueError("cache_hit_flags 与 metrics 长度不一致")
    ok = [m for m in metrics if m.error is None]
    errored = [m for m in metrics if m.error is not None]
    fresh = [
        m for m, hit in zip(metrics, flags)
        if m.error is None and not hit
    ]
    cache_hits = sum(1 for f in flags if f)
    latencies = [m.latency_ms for m in fresh]
    costs = [m.cost_usd for m in fresh]

    metric_means = {
        key: mean(getattr(m, key) for m in ok if getattr(m, key) is not None)
        for key in METRIC_KEYS
    }
    total = len(metrics)
    summary = {
        "samples_total": total,
        "samples_ok": len(ok),
        "samples_error": len(errored),
        "error_rate": (len(errored) / total) if total else None,
        "cache_hits": cache_hits,
        "metrics": metric_means,
        "latency_ms": {
            "mean": mean(latencies),
            "p50": percentile(latencies, 0.5),
            "p90": percentile(latencies, 0.9),
            "p99": percentile(latencies, 0.99),
        },
        "cost": {
            "mean_usd": mean(costs),
            "per_1000": (mean(costs) or 0.0) * 1000 if costs else None,
        },
    }
    summary["samples"] = {
        m.sample_id: sample_view(m) for m in metrics
    }
    return summary


def summarize_run(run: RunResult) -> dict[str, dict]:
    """按 engine_id 分组汇总。predictions 与 metrics 按下标一一对应。"""
    if len(run.predictions) != len(run.metrics):
        raise ValueError(
            "RunResult 内部不一致：predictions 与 metrics 数量不同 "
            f"({len(run.predictions)} != {len(run.metrics)})"
        )
    grouped: dict[str, list[SampleMetrics]] = {}
    hits: dict[str, list[bool]] = {}
    for pred, sm in zip(run.predictions, run.metrics):
        grouped.setdefault(pred.engine_id, []).append(sm)
        hits.setdefault(pred.engine_id, []).append(
            bool((pred.meta or {}).get("cache_hit"))
        )
    return {
        engine_id: engine_summary(rows, hits.get(engine_id))
        for engine_id, rows in grouped.items()
    }
