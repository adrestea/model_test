"""指标插件注册与单样本评分入口。

约定：指标函数签名 `(gt, pred, ctx) -> {字段名: 数值}`，
返回的 key 必须是 `SampleMetrics` 已有字段；新增插件指标需要主控在
`core/types.py` 的 `SampleMetrics` 上加字段（该文件已冻结）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from core.text import NormalizeConfig, split_lines
from core.types import GroundTruth, Line, Prediction, SampleMetrics

log = logging.getLogger(__name__)


@dataclass
class MetricContext:
    """指标计算上下文：归一化口径 + 插件参数（如 box IoU 阈值）。"""

    normalize: NormalizeConfig = field(default_factory=NormalizeConfig)
    options: dict[str, Any] = field(default_factory=dict)


MetricFn = Callable[[GroundTruth, Prediction, MetricContext], dict[str, float | None]]

_METRICS: dict[str, MetricFn] = {}
_LOADED = False

# 允许指标写入的字段（不覆盖身份/计量/错误字段）
_EVAL_FIELDS = {
    "cer", "sub_rate", "del_rate", "ins_rate", "char_recall",
    "line_precision", "line_recall", "line_f1", "box_iou_mean", "exact_match",
}


def register_metric(name: str) -> Callable[[MetricFn], MetricFn]:
    """注册指标插件。同名重复注册直接报错，避免静默覆盖。"""

    def deco(fn: MetricFn) -> MetricFn:
        if name in _METRICS and _METRICS[name] is not fn:
            raise RuntimeError(f"指标重复注册: {name}")
        _METRICS[name] = fn
        return fn

    return deco


def registered_metrics() -> dict[str, MetricFn]:
    """返回当前已注册指标（副本，防止外部修改注册表）。"""
    load_builtin_metrics()
    return dict(_METRICS)


def load_builtin_metrics() -> None:
    """导入内置指标模块触发注册。"""
    global _LOADED
    if _LOADED:
        return
    import importlib

    for mod in ("metrics.text", "metrics.lines"):
        importlib.import_module(mod)
    _LOADED = True


def prediction_text(pred: Prediction) -> str:
    """预测全文：adapter 只填了 lines 时用 lines 拼接，保证 CER 可算。"""
    if pred.text:
        return pred.text
    return "\n".join(l.text for l in (pred.lines or []))


def prediction_lines(pred: Prediction) -> list[Line]:
    """预测行集合：没有行级输出时按换行切全文（无 box）。"""
    if pred.lines:
        return pred.lines
    return [Line(text=t) for t in split_lines(pred.text)]


def evaluate_sample(
    gt: GroundTruth | None,
    pred: Prediction,
    normalize: NormalizeConfig | dict | None = None,
    options: dict[str, Any] | None = None,
) -> SampleMetrics:
    """对单样本跑全部已注册指标。

    - 预测失败：只记录延迟/成本/错误，指标留空（失败样本不参与指标均值）
    - 无 GT：只记录延迟/成本/输出，指标留空
    """
    load_builtin_metrics()
    if isinstance(normalize, NormalizeConfig):
        cfg = normalize
    else:
        cfg = NormalizeConfig.from_dict(normalize)
    ctx = MetricContext(normalize=cfg, options=dict(options or {}))

    sm = SampleMetrics(
        sample_id=pred.sample_id,
        latency_ms=pred.latency_ms,
        cost_usd=pred.cost_usd,
        error=pred.error,
    )
    if pred.error is not None or gt is None:
        return sm

    for name, fn in _METRICS.items():
        try:
            values = fn(gt, pred, ctx)
        except Exception:  # noqa: BLE001 - 单个插件失败不该中断整轮评测
            log.warning("指标计算失败 %s sample=%s", name, pred.sample_id, exc_info=True)
            continue
        for key, value in values.items():
            if key in _EVAL_FIELDS:
                setattr(sm, key, value)
    return sm
