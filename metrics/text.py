"""文本类指标：CER 及其 SUB / DEL / INS 拆解、完整率、完全匹配。"""
from __future__ import annotations

from core.text import edit_stats
from core.types import GroundTruth, Prediction
from metrics import MetricContext, prediction_text, register_metric


@register_metric("text.cer")
def text_cer(
    gt: GroundTruth, pred: Prediction, ctx: MetricContext
) -> dict[str, float | None]:
    """字符级 CER 拆解。归一化在指标层统一做，插件只拿归一化后的文本。"""
    ref = ctx.normalize.apply(gt.text)
    hyp = ctx.normalize.apply(prediction_text(pred))
    stats = edit_stats(ref, hyp)
    return {
        "cer": stats.cer,
        "sub_rate": stats.sub_rate,
        "del_rate": stats.del_rate,
        "ins_rate": stats.ins_rate,
        "char_recall": stats.char_recall,
        "exact_match": stats.exact_match,
    }
