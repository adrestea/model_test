"""行级与定位指标。

行级匹配按归一化后的**行文本多重集合**做，免疫行序差异：
  matched    = Σ_t min(GT 中 t 出现次数, 预测中 t 出现次数)
  precision  = matched / len(预测行)
  recall     = matched / len(GT 行)
  f1         = 2PR / (P + R)

定位（box IoU）在行文本匹配的候选对上做一对一贪心配对，
只统计 GT 有框的行，未命中/IoU 低于阈值的记 0。
"""
from __future__ import annotations

from collections import Counter

from core.types import GroundTruth, Prediction
from metrics import MetricContext, prediction_lines, register_metric

DEFAULT_BOX_IOU_THRESHOLD = 0.5


@register_metric("lines.match")
def line_match(
    gt: GroundTruth, pred: Prediction, ctx: MetricContext
) -> dict[str, float | None]:
    """行级 P/R/F1。GT 只有全文（无 lines）时降级为 None，由全文 CER 兜底。"""
    if not gt.lines:
        return {"line_precision": None, "line_recall": None, "line_f1": None}

    gt_texts = [
        t for t in (ctx.normalize.apply(l.text) for l in gt.lines) if t
    ]
    pred_texts = [
        t for t in (ctx.normalize.apply(l.text) for l in prediction_lines(pred)) if t
    ]

    matched = sum((Counter(gt_texts) & Counter(pred_texts)).values())
    precision = matched / len(pred_texts) if pred_texts else (1.0 if not gt_texts else 0.0)
    recall = matched / len(gt_texts) if gt_texts else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "line_precision": precision,
        "line_recall": recall,
        "line_f1": f1,
    }


@register_metric("lines.box_iou")
def box_iou(
    gt: GroundTruth, pred: Prediction, ctx: MetricContext
) -> dict[str, float | None]:
    """定位 IoU 均值。

    口径：
      - GT 无框，或预测完全没有框 -> None（不参与均值，符合 SampleMetrics 约定）
      - 候选对：行文本归一化后完全相等
      - 一对一贪心：按 IoU 从高到低配对，一个 GT 框、一个预测框各用一次
      - 阈值 τ（默认 0.5，可用 normalize.box_iou_threshold 覆盖）：
        配对 IoU >= τ 记为命中并计入实际 IoU，否则记 0
      - box_iou_mean = Σ(GT 有框行的得分) / GT 有框行数
    """
    if not gt.lines:
        return {"box_iou_mean": None}
    gt_boxes = [
        (ctx.normalize.apply(l.text), l.box)
        for l in gt.lines
        if l.box is not None
    ]
    if not gt_boxes:
        return {"box_iou_mean": None}

    pred_boxes = [
        (ctx.normalize.apply(l.text), l.box)
        for l in prediction_lines(pred)
        if l.box is not None
    ]
    if not pred_boxes:
        return {"box_iou_mean": None}

    threshold = float(
        ctx.options.get("box_iou_threshold", DEFAULT_BOX_IOU_THRESHOLD)
    )
    candidates: list[tuple[float, int, int]] = []
    for gi, (gtext, gbox) in enumerate(gt_boxes):
        if not gtext:
            continue
        for pi, (ptext, pbox) in enumerate(pred_boxes):
            if ptext != gtext:
                continue
            candidates.append((gbox.iou(pbox), gi, pi))
    # 稳定排序：先按 IoU 降序，再按索引，保证同分时结果可复现
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    used_gt: set[int] = set()
    used_pred: set[int] = set()
    score: dict[int, float] = {}
    for iou, gi, pi in candidates:
        if gi in used_gt or pi in used_pred:
            continue
        used_gt.add(gi)
        used_pred.add(pi)
        score[gi] = iou if iou >= threshold else 0.0

    total = sum(score.get(gi, 0.0) for gi in range(len(gt_boxes)))
    return {"box_iou_mean": total / len(gt_boxes)}
