"""基线冻结与对比。

基线文件保存每个引擎的聚合指标 + 单样本指标快照：
  - 聚合指标用于看整体涨跌
  - 单样本快照用于定位"哪些样本变好/变坏"
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.types import RunResult
from runner.aggregate import METRIC_KEYS, summarize_run
from runner.run import load_run, resolve_run_path

BASELINE_VERSION = 1
DEFAULT_BASELINE_DIR = Path("results/baselines")

# 指标方向：True 表示越大越好
HIGHER_IS_BETTER: dict[str, bool] = {
    "cer": False,
    "sub_rate": False,
    "del_rate": False,
    "ins_rate": False,
    "char_recall": True,
    "line_precision": True,
    "line_recall": True,
    "line_f1": True,
    "box_iou_mean": True,
    "exact_match": True,
    "error_rate": False,
    "latency_p50": False,
    "latency_p90": False,
    "latency_p99": False,
    "cost_per_1000": False,
}

METRIC_LABELS: dict[str, str] = {
    "cer": "CER",
    "sub_rate": "错认率 SUB",
    "del_rate": "漏提率 DEL",
    "ins_rate": "多提率 INS",
    "char_recall": "完整率",
    "line_precision": "行准确率",
    "line_recall": "行召回率",
    "line_f1": "行 F1",
    "box_iou_mean": "定位 IoU",
    "exact_match": "完全匹配率",
    "error_rate": "错误率",
    "latency_p50": "延迟 P50(ms)",
    "latency_p90": "延迟 P90(ms)",
    "latency_p99": "延迟 P99(ms)",
    "cost_per_1000": "成本/千样本(USD)",
}

EPS = 1e-9


@dataclass(frozen=True)
class DiffRow:
    engine_id: str
    metric: str
    label: str
    baseline: float | None
    current: float | None
    delta: float | None
    verdict: str          # 变好 / 变坏 / 持平 / 缺失


@dataclass(frozen=True)
class SampleDiff:
    engine_id: str
    sample_id: str
    before: float | None
    after: float | None
    delta: float | None
    verdict: str          # 变好 / 变坏 / 持平 / 缺失
    in_baseline: bool = True
    in_current: bool = True


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def freeze(
    run: RunResult,
    out_path: str | Path | None = None,
    source: str | None = None,
) -> Path:
    """冻结当前 run 为基线。默认写到 results/baselines/<run_name>.json。"""
    target = (
        Path(out_path)
        if out_path
        else DEFAULT_BASELINE_DIR / f"{run.run_name}.json"
    )
    payload = {
        "version": BASELINE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_name": run.run_name,
        "run_created_at": run.created_at,
        "source": source or "",
        "config": {
            "dataset": (run.config or {}).get("dataset"),
            "normalize": (run.config or {}).get("normalize"),
        },
        "engines": summarize_run(run),
    }
    _atomic_write(target, payload)
    return target


def load_baseline(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "engines" not in payload:
        raise ValueError(f"基线文件格式不对（缺 engines）: {path}")
    return payload


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return after - before


def _verdict(
    metric: str, before: float | None, after: float | None
) -> str:
    if before is None or after is None:
        return "缺失"
    delta = after - before
    if abs(delta) <= EPS:
        return "持平"
    good = (delta > 0) if HIGHER_IS_BETTER[metric] else (delta < 0)
    return "变好" if good else "变坏"


def _metric_value(summary: dict, metric: str) -> float | None:
    if metric in METRIC_KEYS:
        return (summary.get("metrics") or {}).get(metric)
    if metric == "error_rate":
        return summary.get("error_rate")
    if metric == "cost_per_1000":
        return (summary.get("cost") or {}).get("per_1000")
    if metric.startswith("latency_"):
        key = metric.removeprefix("latency_")
        return (summary.get("latency_ms") or {}).get(key)
    return None


def compare(
    run: RunResult, baseline: dict
) -> tuple[list[DiffRow], list[SampleDiff]]:
    """对比当前 run 与基线，返回 (指标行, 样本行)。"""
    current = summarize_run(run)
    before_engines: dict[str, dict] = baseline.get("engines") or {}
    engines = sorted(set(current) | set(before_engines))
    metrics = list(METRIC_KEYS) + [
        "error_rate", "latency_p50", "latency_p90", "latency_p99", "cost_per_1000",
    ]

    rows: list[DiffRow] = []
    for engine_id in engines:
        cur = current.get(engine_id) or {}
        old = before_engines.get(engine_id) or {}
        # 全部样本命中缓存时，本次没有真实耗时/计费样本，不能当成“变好”或“缺失”
        all_cached = (
            (cur.get("cache_hits") or 0) > 0
            and cur.get("cache_hits") == cur.get("samples_total")
        )
        for metric in metrics:
            b = _metric_value(old, metric)
            c = _metric_value(cur, metric)
            verdict = _verdict(metric, b, c)
            if verdict == "缺失" and all_cached and metric in (
                "latency_p50", "latency_p90", "latency_p99", "cost_per_1000",
            ):
                verdict = "缓存命中"
            rows.append(
                DiffRow(
                    engine_id=engine_id,
                    metric=metric,
                    label=METRIC_LABELS[metric],
                    baseline=b,
                    current=c,
                    delta=_delta(b, c),
                    verdict=verdict,
                )
            )

    samples: list[SampleDiff] = []
    for engine_id in engines:
        cur = (current.get(engine_id) or {}).get("samples") or {}
        old = (before_engines.get(engine_id) or {}).get("samples") or {}
        for sid in sorted(set(cur) | set(old)):
            b = (old.get(sid) or {}).get("cer")
            c = (cur.get(sid) or {}).get("cer")
            samples.append(
                SampleDiff(
                    engine_id=engine_id,
                    sample_id=sid,
                    before=b,
                    after=c,
                    delta=_delta(b, c),
                    verdict=_verdict("cer", b, c),
                    in_baseline=sid in old,
                    in_current=sid in cur,
                )
            )
    return rows, samples


def diff_report(run: RunResult, baseline: dict) -> dict:
    rows, samples = compare(run, baseline)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.engine_id, []).append(asdict(row))
    counts = {"变好": 0, "变坏": 0, "持平": 0, "缺失": 0}
    for s in samples:
        counts[s.verdict] = counts.get(s.verdict, 0) + 1
    # 样本集是否一致：不一致时均值涨跌含样本构成变化，需要提醒用户
    sample_sets: dict[str, dict[str, int]] = {}
    for s in samples:
        item = sample_sets.setdefault(
            s.engine_id, {"baseline": 0, "current": 0, "common": 0}
        )
        if s.in_baseline:
            item["baseline"] += 1
        if s.in_current:
            item["current"] += 1
        if s.in_baseline and s.in_current:
            item["common"] += 1
    return {
        "run_name": run.run_name,
        "baseline_run_name": baseline.get("run_name"),
        "metric_rows": [asdict(r) for r in rows],
        "engines": grouped,
        "sample_changes": {
            "counts": counts,
            "rows": [asdict(s) for s in samples],
        },
        "sample_sets": sample_sets,
        "sample_set_changed": any(
            item["baseline"] != item["current"] for item in sample_sets.values()
        ),
    }


def resolve_baseline(path: str | Path) -> Path:
    p = Path(path)
    if p.is_file():
        return p
    cand = DEFAULT_BASELINE_DIR / f"{path}.json"
    if cand.is_file():
        return cand
    raise FileNotFoundError(f"找不到基线文件: {path}")


def run_and_baseline(run_arg: str | Path, baseline_arg: str | Path) -> tuple[RunResult, dict, Path]:
    """CLI 用：解析 run 与 baseline 路径并读取。"""
    run_path = resolve_run_path(run_arg)
    baseline_path = resolve_baseline(baseline_arg)
    return load_run(run_path), load_baseline(baseline_path), run_path
