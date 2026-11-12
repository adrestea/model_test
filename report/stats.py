"""报告统计：引擎总榜、分场景分组、逐样本对照、延迟分布、成本与选型辅助。

只读 RunResult + DatasetContext，不调引擎、不重新推理。
指标一律来自 run.json 里的 SampleMetrics（与 runner/metrics 同口径）；
字符绝对值（漏提/多提/错认多少个字）用 core.text 重新数一遍，
因为 SampleMetrics 只存比率，报告要展示"漏了 12 个字"这种直观数字。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.types import Prediction, RunResult, SampleMetrics

from report.diff import DiffResult, diff_text
from report.loader import (
    DatasetContext,
    grouped_runs,
    media_path_for,
    normalize_config,
)

# 报告里所有可排序的指标 → 中文列名（排序方向：True 表示越大越好）
SORT_KEYS: dict[str, tuple[str, bool]] = {
    "cer": ("CER", False),
    "char_recall": ("完整率", True),
    "del_rate": ("漏提率", False),
    "ins_rate": ("多提率", False),
    "sub_rate": ("错认率", False),
    "line_f1": ("行级 F1", True),
    "exact_match": ("完全匹配率", True),
    "latency": ("平均延迟", False),
    "cost": ("每千张成本", False),
    "accuracy": ("准确率", True),
}

# 成本与选型默认用「完整率」当准确率：它直接对应"文字提全"这个业务目标
DEFAULT_ACCURACY_METRIC = "char_recall"

ERROR_KINDS = ("sub", "del", "ins")


def _mean(values: Iterable[float | None]) -> float | None:
    data = [v for v in values if v is not None]
    return sum(data) / len(data) if data else None


def percentile(values: Iterable[float], q: float) -> float | None:
    """线性插值分位数（与 runner.aggregate.percentile 同算法）。"""
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


# --------------------------------------------------------------------------
# 单引擎统计
# --------------------------------------------------------------------------
@dataclass
class EngineStat:
    engine_id: str
    engine_type: str = ""
    samples_total: int = 0
    samples_ok: int = 0
    samples_error: int = 0
    cache_hits: int = 0
    metrics: dict[str, float | None] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    latency: dict[str, float | None] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)
    cost_mean_usd: float | None = None
    cost_total_usd: float | None = None
    per_1000_usd: float | None = None
    per_1000_cny: float | None = None
    per_1000_min_usd: float | None = None
    per_1000_min_cny: float | None = None
    throughput_per_min: float | None = None
    accuracy: float | None = None
    pareto: bool = False
    marginal_cost_per_pp_usd: float | None = None
    note: str = ""

    def value(self, key: str) -> float | None:
        """统一取数：指标均值 / 延迟 / 每千张成本 / 准确率。"""
        if key == "latency":
            return self.latency.get("mean")
        if key == "cost":
            return self.per_1000_usd
        if key == "accuracy":
            return self.accuracy
        return self.metrics.get(key)


def _engine_meta(run: RunResult, engine_id: str) -> dict[str, Any]:
    for cfg in (run.config or {}).get("engines") or []:
        if (cfg.get("id") or cfg.get("type")) == engine_id:
            return cfg
    return {}


def build_engine_stats(
    run: RunResult,
    ctx: DatasetContext | None = None,
    rate: float = 7.2,
    accuracy_metric: str = DEFAULT_ACCURACY_METRIC,
) -> list[EngineStat]:
    """一次算出所有引擎的统计量（不做排序，排序交给调用方）。"""
    grouped = grouped_runs(run)
    norm = normalize_config(run)
    gts = (ctx.ground_truth if ctx else {}) or {}
    stats: list[EngineStat] = []

    for engine_id, by_sample in grouped.items():
        cfg = _engine_meta(run, engine_id)
        stat = EngineStat(engine_id=engine_id, engine_type=str(cfg.get("type") or ""))
        rows = list(by_sample.values())
        stat.samples_total = len(rows)
        errors = [sm for _, sm in rows if sm.error is not None]
        oks = [sm for _, sm in rows if sm.error is None]
        stat.samples_error = len(errors)
        stat.samples_ok = len(oks)

        metric_keys = (
            "cer", "sub_rate", "del_rate", "ins_rate", "char_recall",
            "line_precision", "line_recall", "line_f1", "box_iou_mean", "exact_match",
        )
        stat.metrics = {
            k: _mean(getattr(sm, k) for sm in oks if getattr(sm, k) is not None)
            for k in metric_keys
        }
        err_ids = [sm.sample_id for sm in errors]
        stat.note = f"{len(err_ids)} 个样本失败（{', '.join(err_ids[:3])}…）" if err_ids else ""

        # 字符级绝对计数：报告要用"漏提 12 字"这种直观口径
        counts = {k: 0 for k in ("ref_chars", "hyp_chars", *ERROR_KINDS, "errors")}
        counted = 0
        for pred, _sm in rows:
            gt = gts.get(pred.sample_id)
            if gt is None or pred.error is not None:
                continue
            d = diff_text(gt.text, pred.text, norm)
            counts["ref_chars"] += d.stats.ref_len
            counts["hyp_chars"] += d.stats.hyp_len
            counts["sub"] += d.stats.sub
            counts["del"] += d.stats.delete
            counts["ins"] += d.stats.insert
            counts["errors"] += d.stats.distance
            counted += 1
        stat.counts = counts if counted else {}

        # 延迟/成本：缓存命中样本不能计入效率（否则数字会假性变好）
        fresh = [
            sm for pred, sm in rows
            if sm.error is None and not (pred.meta or {}).get("cache_hit")
        ]
        stat.cache_hits = sum(1 for pred, _ in rows if (pred.meta or {}).get("cache_hit"))
        lat = [sm.latency_ms for sm in fresh]
        stat.latencies = lat
        stat.latency = {
            "mean": _mean(lat),
            "p50": percentile(lat, 0.5),
            "p90": percentile(lat, 0.9),
            "p99": percentile(lat, 0.99),
            "min": min(lat) if lat else None,
            "max": max(lat) if lat else None,
            "n": len(lat),
        }
        costs = [sm.cost_usd for sm in fresh]
        stat.cost_mean_usd = _mean(costs)
        stat.cost_total_usd = sum(costs) if costs else None
        if stat.cost_mean_usd is not None:
            stat.per_1000_usd = stat.cost_mean_usd * 1000
            stat.per_1000_cny = stat.per_1000_usd * rate
        mean_lat = stat.latency.get("mean")
        if mean_lat and mean_lat > 0:
            stat.throughput_per_min = 60000.0 / mean_lat
            if stat.cost_mean_usd is not None:
                # 每千分钟"机时"成本 = 单样本成本 / 单样本机时(分钟) * 1000
                stat.per_1000_min_usd = (
                    stat.cost_mean_usd / (mean_lat / 60000.0) * 1000
                )
                stat.per_1000_min_cny = stat.per_1000_min_usd * rate

        stat.accuracy = stat.metrics.get(accuracy_metric)
        if stat.accuracy is None and accuracy_metric == DEFAULT_ACCURACY_METRIC:
            cer = stat.metrics.get("cer")
            stat.accuracy = None if cer is None else max(0.0, 1.0 - cer)
        stats.append(stat)

    _annotate_selection(stats)
    return stats


def _annotate_selection(stats: list[EngineStat]) -> None:
    """帕累托前沿 + 「每提升 1 个百分点准确率需要多少钱」。

    前沿定义：没有别的引擎同时做到「准确率不低 且 每千张成本不高」（至少一项严格更好）。
    边际成本以「最便宜的引擎」为基线：Δ成本 / Δ准确率(百分点)。
    """
    scored = [s for s in stats if s.accuracy is not None]
    for s in stats:
        s.pareto = False
        s.marginal_cost_per_pp_usd = None
    if not scored:
        return

    for s in scored:
        dominated = False
        for other in scored:
            if other is s:
                continue
            cost_s = s.per_1000_usd or 0.0
            cost_o = other.per_1000_usd or 0.0
            if other.accuracy >= s.accuracy and cost_o <= cost_s and (
                other.accuracy > s.accuracy or cost_o < cost_s
            ):
                dominated = True
                break
        s.pareto = not dominated

    base = min(scored, key=lambda s: (s.per_1000_usd or 0.0, -s.accuracy))
    base_cost = base.per_1000_usd or 0.0
    base_acc_pp = base.accuracy * 100
    for s in scored:
        gain_pp = s.accuracy * 100 - base_acc_pp
        extra = (s.per_1000_usd or 0.0) - base_cost
        if gain_pp <= 0.05:
            s.marginal_cost_per_pp_usd = None
            continue
        s.marginal_cost_per_pp_usd = extra / gain_pp


def sort_engine_stats(stats: list[EngineStat], sort_key: str = "cer") -> list[EngineStat]:
    """按指定指标排序；None 一律排最后（缺 GT / 无成本的引擎不该占榜首）。"""
    key = sort_key if sort_key in SORT_KEYS else "cer"
    _, higher_better = SORT_KEYS[key]

    def sort_val(s: EngineStat) -> tuple[int, float]:
        v = s.value(key)
        if v is None:
            return (1, 0.0)
        return (0, -v if higher_better else v)

    return sorted(stats, key=sort_val)


# --------------------------------------------------------------------------
# 分场景分组
# --------------------------------------------------------------------------
def build_scene_stats(
    run: RunResult,
    ctx: DatasetContext | None,
    rate: float = 7.2,
    accuracy_metric: str = DEFAULT_ACCURACY_METRIC,
) -> dict[str, list[EngineStat]]:
    """按场景切片：同一批引擎在每个场景内单独汇总，用于定位"哪个场景掉分"。"""
    if ctx is None or not ctx.scenes:
        return {}
    scenes = sorted({ctx.scenes.get(s, "未分组") for s in dict.fromkeys(run.samples)})
    out: dict[str, list[EngineStat]] = {}
    for scene in scenes:
        ids = [s for s in dict.fromkeys(run.samples) if ctx.scenes.get(s, "未分组") == scene]
        if not ids:
            continue
        sub = _slice_run(run, ids)
        out[scene] = sort_engine_stats(
            build_engine_stats(sub, ctx, rate=rate, accuracy_metric=accuracy_metric)
        )
    return out


def _slice_run(run: RunResult, sample_ids: list[str]) -> RunResult:
    want = set(sample_ids)
    keep = [i for i, p in enumerate(run.predictions) if p.sample_id in want]
    return RunResult(
        run_name=run.run_name,
        config=run.config,
        samples=[s for s in run.samples if s in want],
        predictions=[run.predictions[i] for i in keep],
        metrics=[run.metrics[i] for i in keep],
        created_at=run.created_at,
        env=run.env,
    )


# --------------------------------------------------------------------------
# 逐样本对照
# --------------------------------------------------------------------------
@dataclass
class EngineCell:
    """某个引擎在某个样本上的展示单元。"""

    engine_id: str
    prediction: Prediction
    metrics: SampleMetrics
    diff: DiffResult | None = None

    @property
    def ok(self) -> bool:
        return self.prediction.error is None

    @property
    def text(self) -> str:
        return self.prediction.text or ""


@dataclass
class SampleRow:
    sample_id: str
    scene: str = "未分组"
    gt_text: str | None = None
    gt_lines: list[str] = field(default_factory=list)
    media: str | None = None
    cells: dict[str, EngineCell] = field(default_factory=dict)

    def worst_cer(self) -> float | None:
        vals = [c.metrics.cer for c in self.cells.values() if c.metrics.cer is not None]
        return max(vals) if vals else None


def build_sample_rows(
    run: RunResult,
    ctx: DatasetContext | None,
    engine_order: list[str] | None = None,
    limit: int | None = None,
) -> list[SampleRow]:
    norm = normalize_config(run)
    gts = (ctx.ground_truth if ctx else {}) or {}
    order = engine_order or list(grouped_runs(run))
    rows: list[SampleRow] = []
    for sample_id in dict.fromkeys(run.samples):
        row = SampleRow(
            sample_id=sample_id,
            scene=(ctx.scenes.get(sample_id, "未分组") if ctx else "未分组"),
        )
        gt = gts.get(sample_id)
        if gt is not None:
            row.gt_text = gt.text
            row.gt_lines = [l.text for l in (gt.lines or [])]
        if ctx is not None:
            p = media_path_for(ctx, sample_id)
            row.media = str(p) if p else None
        for engine_id in order:
            pair = (grouped_runs(run).get(engine_id) or {}).get(sample_id)
            if pair is None:
                continue
            pred, sm = pair
            diff = None
            if gt is not None and pred.error is None:
                diff = diff_text(gt.text, pred.text, norm)
            row.cells[engine_id] = EngineCell(
                engine_id=engine_id, prediction=pred, metrics=sm, diff=diff
            )
        rows.append(row)
    if limit:
        rows = rows[:limit]
    return rows


# --------------------------------------------------------------------------
# 延迟分布
# --------------------------------------------------------------------------
def latency_histogram(values: list[float], bins: int = 8) -> list[tuple[str, int, float]]:
    """等宽分桶直方图 → [(区间标签, 计数, 占比)]，用于无 JS 的 CSS 柱状图。"""
    data = [v for v in values if v is not None]
    if not data:
        return []
    lo, hi = min(data), max(data)
    if hi <= lo:
        return [(f"{lo:.0f} ms", len(data), 1.0)]
    n = max(1, min(bins, len(data)))
    width = (hi - lo) / n
    buckets = [0] * n
    for v in data:
        idx = min(n - 1, int((v - lo) / width))
        buckets[idx] += 1
    total = len(data)
    return [
        (f"{lo + i * width:.0f}–{lo + (i + 1) * width:.0f} ms", c, c / total)
        for i, c in enumerate(buckets)
    ]


def latency_rows(stats: list[EngineStat]) -> list[dict[str, Any]]:
    """延迟汇总表 + 直方图，供 HTML/Markdown 共用。"""
    out = []
    for s in stats:
        out.append({
            "engine_id": s.engine_id,
            "n": s.latency.get("n") or 0,
            "mean": s.latency.get("mean"),
            "p50": s.latency.get("p50"),
            "p90": s.latency.get("p90"),
            "p99": s.latency.get("p99"),
            "max": s.latency.get("max"),
            "throughput": s.throughput_per_min,
            "hist": latency_histogram(s.latencies),
        })
    return out


# --------------------------------------------------------------------------
# 成本核算
# --------------------------------------------------------------------------
def cost_rows(stats: list[EngineStat], rate: float, accuracy_metric: str) -> list[dict[str, Any]]:
    """成本核算表：每千张 / 每千分钟 / 边际成本 / 帕累托标记。"""
    label = SORT_KEYS.get(accuracy_metric, ("准确率", True))[0]
    rows = []
    for s in stats:
        rows.append({
            "engine_id": s.engine_id,
            "engine_type": s.engine_type,
            "cost_mean_usd": s.cost_mean_usd,
            "per_1000_usd": s.per_1000_usd,
            "per_1000_cny": s.per_1000_cny,
            "per_1000_min_usd": s.per_1000_min_usd,
            "per_1000_min_cny": s.per_1000_min_cny,
            "throughput": s.throughput_per_min,
            "accuracy": s.accuracy,
            "accuracy_label": label,
            "marginal_per_pp_usd": s.marginal_cost_per_pp_usd,
            "pareto": s.pareto,
            "note": s.note,
        })
    return rows


def selection_summary(stats: list[EngineStat], rate: float,
                      accuracy_metric: str) -> dict[str, Any]:
    """一句话选型结论（报告顶部摘要用）。"""
    scored = [s for s in stats if s.accuracy is not None]
    label = SORT_KEYS.get(accuracy_metric, ("准确率", True))[0]
    summary: dict[str, Any] = {"accuracy_label": label, "lines": []}
    if not scored:
        summary["lines"].append("本次运行没有可用的准确率数据（缺标注或全部失败），只能看延迟与成本。")
        return summary

    best_acc = max(scored, key=lambda s: (s.accuracy, -(s.per_1000_usd or 0.0)))
    cheapest = min(scored, key=lambda s: (s.per_1000_usd or 0.0, -s.accuracy))
    frontier = [s for s in scored if s.pareto]
    summary.update({
        "best_accuracy": best_acc.engine_id,
        "cheapest": cheapest.engine_id,
        "frontier": [s.engine_id for s in frontier],
    })
    summary["lines"].append(
        f"{label}最高：{best_acc.engine_id}（{best_acc.accuracy * 100:.2f}%），"
        f"每千张成本 {_fmt_money(best_acc.per_1000_usd, rate)}。"
    )
    summary["lines"].append(
        f"最省钱：{cheapest.engine_id}（{_fmt_money(cheapest.per_1000_usd, rate)}/千张），"
        f"{label} {cheapest.accuracy * 100:.2f}%。"
    )
    if frontier:
        summary["lines"].append(
            "帕累托前沿（没有更便宜且更准的引擎）：" + "、".join(s.engine_id for s in frontier) + "。"
        )
    if best_acc.engine_id != cheapest.engine_id:
        gain = (best_acc.accuracy - cheapest.accuracy) * 100
        extra = (best_acc.per_1000_usd or 0.0) - (cheapest.per_1000_usd or 0.0)
        if gain > 0.05:
            summary["lines"].append(
                f"从 {cheapest.engine_id} 升级到 {best_acc.engine_id}："
                f"{label} +{gain:.2f} 个百分点，每千张多花 {_fmt_money(extra, rate)}"
                f"（每提升 1 个百分点约 {_fmt_money(extra / gain, rate)}）。"
            )
        else:
            summary["lines"].append(
                f"{best_acc.engine_id} 相比 {cheapest.engine_id} 没有准确率优势，"
                "按「花更少钱办同样事」原则应选便宜的。"
            )
    elif (cheapest.per_1000_usd or 0.0) == 0:
        summary["lines"].append("本次运行的引擎成本均为 0（本地部署），成本列只用于说明口径。")
    return summary


def _fmt_money(usd: float | None, rate: float) -> str:
    if usd is None:
        return "—"
    return f"${usd:,.4f} / ¥{usd * rate:,.4f}"
