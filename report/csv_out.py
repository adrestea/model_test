"""CSV 导出：给 Excel / BI 继续算账用。

四个文件，长表设计（一行一个引擎×样本），不做合并单元格：
  engines.csv  引擎总榜（一行一个引擎）
  samples.csv  逐样本长表（一行一个引擎×样本，含 diff 纯文本标记）
  scenes.csv   分场景（一行一个场景×引擎）
  costs.csv    成本核算（一行一个引擎）

编码用 utf-8-sig：Excel 双击打开中文不乱码；pandas 读取请显式
`encoding="utf-8-sig"`。
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from report.format import pct
from report.render import ReportBundle
from report.stats import SORT_KEYS

ENCODING = "utf-8-sig"


def _write(path: Path, headers: list[str], rows: Iterable[list[Any]]) -> Path:
    with path.open("w", encoding=ENCODING, newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
    return path


def _r(value: float | None, digits: int = 4) -> float | str:
    """数值列保留精度写入，None 留空（Excel 里空才是空，别塞 0）。"""
    return "" if value is None else round(value, digits)


def write_engines(bundle: ReportBundle, target: Path) -> Path:
    headers = [
        "排名", "引擎", "类型", "样本数", "成功数", "失败数", "缓存命中",
        "CER", "错认率", "漏提率", "多提率", "完整率",
        "行级精确率", "行级召回率", "行级F1", "定位IoU", "完全匹配率",
        "GT字符数", "漏提字数", "多提字数", "错认字数", "编辑距离",
        "平均延迟ms", "P50延迟ms", "P90延迟ms", "P99延迟ms",
        "吞吐_张每分钟", "单张成本USD", "每千张成本USD", "每千张成本CNY",
        "每千分钟成本USD", "每千分钟成本CNY",
        f"{SORT_KEYS[bundle.opts.accuracy_metric][0]}", "每提升1pp成本USD每千张", "帕累托前沿",
    ]
    rows = []
    for i, s in enumerate(bundle.engines, start=1):
        c = s.counts or {}
        rows.append([
            i, s.engine_id, s.engine_type, s.samples_total, s.samples_ok,
            s.samples_error, s.cache_hits,
            _r(s.metrics.get("cer")), _r(s.metrics.get("sub_rate")),
            _r(s.metrics.get("del_rate")), _r(s.metrics.get("ins_rate")),
            _r(s.metrics.get("char_recall")),
            _r(s.metrics.get("line_precision")), _r(s.metrics.get("line_recall")),
            _r(s.metrics.get("line_f1")), _r(s.metrics.get("box_iou_mean")),
            _r(s.metrics.get("exact_match")),
            c.get("ref_chars", ""), c.get("del", ""), c.get("ins", ""),
            c.get("sub", ""), c.get("errors", ""),
            _r(s.latency.get("mean"), 2), _r(s.latency.get("p50"), 2),
            _r(s.latency.get("p90"), 2), _r(s.latency.get("p99"), 2),
            _r(s.throughput_per_min, 2),
            _r(s.cost_mean_usd, 8), _r(s.per_1000_usd, 6), _r(s.per_1000_cny, 6),
            _r(s.per_1000_min_usd, 6), _r(s.per_1000_min_cny, 6),
            _r(s.accuracy), _r(s.marginal_cost_per_pp_usd, 6),
            "是" if s.pareto else "否",
        ])
    return _write(target / "engines.csv", headers, rows)


def write_samples(bundle: ReportBundle, target: Path) -> Path:
    headers = [
        "样本ID", "场景", "引擎", "是否有GT", "是否成功", "错误信息",
        "CER", "错认率", "漏提率", "多提率", "完整率", "行级F1", "定位IoU", "完全匹配",
        "GT字符数", "预测字符数", "漏提字数", "多提字数", "错认字数", "编辑距离",
        "延迟ms", "成本USD", "GT文本", "预测文本", "GT_diff视图", "预测_diff视图",
    ]
    rows = []
    for row in bundle.samples:
        for engine_id, cell in row.cells.items():
            sm = cell.metrics
            pred = cell.prediction
            d = cell.diff
            rows.append([
                row.sample_id, row.scene, engine_id,
                "是" if row.gt_text is not None else "否",
                "否" if pred.error else "是", pred.error or "",
                _r(sm.cer), _r(sm.sub_rate), _r(sm.del_rate), _r(sm.ins_rate),
                _r(sm.char_recall), _r(sm.line_f1), _r(sm.box_iou_mean),
                _r(sm.exact_match),
                d.stats.ref_len if d else "",
                d.stats.hyp_len if d else (len(pred.text) if pred.text else 0),
                d.stats.delete if d else "", d.stats.insert if d else "",
                d.stats.sub if d else "", d.stats.distance if d else "",
                _r(sm.latency_ms, 2), _r(sm.cost_usd, 8),
                (row.gt_text or "").replace("\n", "\u23ce"),
                (pred.text or "").replace("\n", "\u23ce"),
                d.gt_plain if d else "",
                d.pred_plain if d else "",
            ])
    return _write(target / "samples.csv", headers, rows)


def write_scenes(bundle: ReportBundle, target: Path) -> Path:
    headers = [
        "场景", "引擎", "样本数", "成功数", "CER", "完整率", "漏提率", "多提率",
        "行级F1", "平均延迟ms", "每千张成本USD", "每千张成本CNY",
    ]
    rows = []
    for scene, engines in bundle.scenes.items():
        for s in engines:
            rows.append([
                scene, s.engine_id, s.samples_total, s.samples_ok,
                _r(s.metrics.get("cer")), _r(s.metrics.get("char_recall")),
                _r(s.metrics.get("del_rate")), _r(s.metrics.get("ins_rate")),
                _r(s.metrics.get("line_f1")), _r(s.latency.get("mean"), 2),
                _r(s.per_1000_usd, 6), _r(s.per_1000_cny, 6),
            ])
    return _write(target / "scenes.csv", headers, rows)


def write_costs(bundle: ReportBundle, target: Path) -> Path:
    label = bundle.accuracy_label
    headers = [
        "引擎", "类型", "单张成本USD", "每千张成本USD", "每千张成本CNY",
        "每千分钟成本USD", "每千分钟成本CNY", "吞吐_张每分钟",
        f"{label}", f"每提升1pp成本USD每千张", "帕累托前沿", "汇率USD_CNY", "备注",
    ]
    rows = []
    for r in bundle.cost_table():
        rows.append([
            r["engine_id"], r["engine_type"], _r(r["cost_mean_usd"], 8),
            _r(r["per_1000_usd"], 6), _r(r["per_1000_cny"], 6),
            _r(r["per_1000_min_usd"], 6), _r(r["per_1000_min_cny"], 6),
            _r(r["throughput"], 2), _r(r["accuracy"]),
            _r(r["marginal_per_pp_usd"], 6),
            "是" if r["pareto"] else "否", bundle.opts.rate, r["note"],
        ])
    return _write(target / "costs.csv", headers, rows)


def write_csvs(bundle: ReportBundle, target: str | Path) -> list[Path]:
    """写全部 CSV，返回落地文件列表（顺序固定，便于测试断言）。"""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    return [
        write_engines(bundle, target),
        write_samples(bundle, target),
        write_scenes(bundle, target),
        write_costs(bundle, target),
    ]
