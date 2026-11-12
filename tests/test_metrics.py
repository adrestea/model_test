"""指标插件测试：CER 拆解、完整率、行级 P/R/F1、定位 IoU。"""
from __future__ import annotations

import pytest

from core.text import NormalizeConfig
from core.types import Box, GroundTruth, Line, Prediction
from metrics import evaluate_sample

# 精确数值测试关闭归一化，避免口径干扰
NORM = NormalizeConfig(
    strip_whitespace=False, lower=False, unify_punct=False, drop_punct=False
)


def make_gt(text: str | None = None, lines: list[Line] | None = None) -> GroundTruth:
    return GroundTruth(sample_id="s1", text=text, lines=lines)


def make_pred(
    text: str = "",
    lines: list[Line] | None = None,
    error: str | None = None,
    latency_ms: float = 1.0,
    cost_usd: float = 0.0,
) -> Prediction:
    return Prediction(
        engine_id="e1",
        sample_id="s1",
        task="recognize",
        text=text,
        lines=lines,
        error=error,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )


def test_perfect_prediction() -> None:
    sm = evaluate_sample(make_gt("abcd"), make_pred("abcd"), NORM)
    assert sm.cer == 0.0
    assert sm.char_recall == 1.0
    assert sm.exact_match == 1.0
    assert sm.error is None


def test_deletion_lowers_char_recall() -> None:
    sm = evaluate_sample(make_gt("abcd"), make_pred("abd"), NORM)
    assert sm.cer == 0.25
    assert sm.del_rate == 0.25
    assert sm.sub_rate == 0.0
    assert sm.char_recall == 0.75
    assert sm.exact_match == 0.0


def test_insertion_does_not_lower_char_recall() -> None:
    sm = evaluate_sample(make_gt("abcd"), make_pred("abxcd"), NORM)
    assert sm.cer == 0.25
    assert sm.ins_rate == 0.25
    assert sm.char_recall == 1.0


def test_error_prediction_has_no_metrics() -> None:
    sm = evaluate_sample(
        make_gt("abcd"), make_pred("", error="RuntimeError: boom", latency_ms=12.0)
    )
    assert sm.error == "RuntimeError: boom"
    assert sm.latency_ms == 12.0
    assert sm.cer is None
    assert sm.char_recall is None


def test_missing_gt_has_no_metrics() -> None:
    sm = evaluate_sample(None, make_pred("abcd"), NORM)
    assert sm.cer is None
    assert sm.error is None


def test_norm_dict_is_accepted() -> None:
    sm = evaluate_sample(
        make_gt("A B"), make_pred("AB"),
        {"strip_whitespace": True, "unify_punct": False},
    )
    assert sm.cer == 0.0


def test_line_metrics_are_order_insensitive() -> None:
    lines = [Line("第一行"), Line("第二行"), Line("第三行")]
    pred_lines = [Line("第三行"), Line("第一行"), Line("第二行")]
    sm = evaluate_sample(
        make_gt("第一行\n第二行\n第三行", lines), make_pred("", pred_lines), NORM
    )
    assert sm.line_precision == 1.0
    assert sm.line_recall == 1.0
    assert sm.line_f1 == 1.0


def test_line_metrics_multiset_duplicates() -> None:
    gt_lines = [Line("A"), Line("A"), Line("B")]
    pred_lines = [Line("A"), Line("B")]
    sm = evaluate_sample(make_gt("A\nA\nB", gt_lines), make_pred("", pred_lines), NORM)
    assert sm.line_precision == 1.0
    assert sm.line_recall == pytest.approx(2 / 3)
    assert sm.line_f1 == pytest.approx(0.8)


def test_line_metrics_from_text_when_pred_has_no_lines() -> None:
    gt_lines = [Line("A"), Line("B")]
    sm = evaluate_sample(make_gt("A\nB", gt_lines), make_pred("A\nB"), NORM)
    assert sm.line_f1 == 1.0


def test_line_metrics_none_without_gt_lines() -> None:
    sm = evaluate_sample(make_gt("A\nB"), make_pred("A\nB"), NORM)
    assert sm.line_precision is None
    assert sm.line_recall is None
    assert sm.line_f1 is None
    assert sm.cer == 0.0


def test_prediction_text_falls_back_to_lines() -> None:
    sm = evaluate_sample(make_gt("AB"), make_pred("", [Line("A"), Line("B")]), NORM)
    assert sm.cer == 0.5  # "AB" vs "A\nB"：多提一个换行
    sm2 = evaluate_sample(
        make_gt("A\nB"),
        make_pred("", [Line("A"), Line("B")]),
        {"strip_whitespace": False},
    )
    assert sm2.cer == 0.0


def test_box_iou_mean_and_threshold() -> None:
    gt_lines = [
        Line("A", Box(0, 0, 10, 10)),
        Line("B", Box(0, 20, 10, 30)),
    ]
    pred_lines = [
        Line("A", Box(0, 0, 10, 10)),
        Line("B", Box(0, 25, 10, 35)),  # IoU = 50/150 ≈ 0.333
    ]
    sm = evaluate_sample(
        make_gt("A\nB", gt_lines), make_pred("", pred_lines), NORM
    )
    # B 低于默认阈值 0.5 -> 记 0；A 满分
    assert sm.box_iou_mean == pytest.approx(0.5)

    loose = evaluate_sample(
        make_gt("A\nB", gt_lines), make_pred("", pred_lines), NORM,
        options={"box_iou_threshold": 0.3},
    )
    assert loose.box_iou_mean == pytest.approx((1.0 + 50 / 150) / 2)


def test_box_iou_none_when_either_side_has_no_box() -> None:
    gt_lines = [Line("A", Box(0, 0, 10, 10))]
    sm = evaluate_sample(make_gt("A", gt_lines), make_pred("A"), NORM)
    assert sm.box_iou_mean is None

    pred_lines = [Line("A", Box(0, 0, 10, 10))]
    sm2 = evaluate_sample(make_gt("A"), make_pred("", pred_lines), NORM)
    assert sm2.box_iou_mean is None


def test_box_iou_text_mismatch_scores_zero() -> None:
    gt_lines = [Line("A", Box(0, 0, 10, 10)), Line("B", Box(0, 20, 10, 30))]
    pred_lines = [Line("X", Box(0, 0, 10, 10)), Line("Y", Box(0, 20, 10, 30))]
    sm = evaluate_sample(
        make_gt("A\nB", gt_lines), make_pred("", pred_lines), NORM
    )
    assert sm.box_iou_mean == 0.0


def test_box_iou_greedy_one_to_one() -> None:
    # 两个 GT 框文本相同，预测也有两个：应该一对一配对而不是都算给同一个
    gt_lines = [Line("A", Box(0, 0, 10, 10)), Line("A", Box(0, 100, 10, 110))]
    pred_lines = [Line("A", Box(0, 0, 10, 10)), Line("A", Box(0, 100, 10, 110))]
    sm = evaluate_sample(
        make_gt("A\nA", gt_lines), make_pred("", pred_lines), NORM
    )
    assert sm.box_iou_mean == pytest.approx(1.0)
