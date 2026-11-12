"""字符级 diff 渲染：把 core.text 的对齐结果变成可读的红/蓝/黄高亮。

配色口径（与指标一一对应，避免"看图"与"看数"打架）：
  漏提 DEL  -> 红   GT 有、预测没有
  多提 INS  -> 蓝   预测多出来、GT 没有
  错认 SUB  -> 黄   GT 有这个字但被认成了别的字

本模块只做字符串拼接，不碰 IO、不依赖三方库。
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from core.text import EditOp, NormalizeConfig, align, edit_stats

# 三种错误对应的 CSS 类名，报告模板与测试共用
CLS_DEL = "d-del"   # 漏提：红
CLS_INS = "d-ins"   # 多提：蓝
CLS_SUB = "d-sub"   # 错认：黄
CLS_EQ = "d-eq"

LEGEND = (
    (CLS_DEL, "漏提（GT 有、预测无）"),
    (CLS_INS, "多提（预测多出）"),
    (CLS_SUB, "错认（认成了别的字）"),
)


@dataclass(frozen=True)
class DiffResult:
    """一次对照的完整产物：两侧高亮字符串 + 字符级统计。"""

    gt_html: str
    pred_html: str
    gt_plain: str
    pred_plain: str
    stats: object            # core.text.EditStats
    ops: list[EditOp]

    @property
    def is_perfect(self) -> bool:
        return self.stats.distance == 0


def _esc(ch: str) -> str:
    return html.escape(ch, quote=False)


def _span(cls: str, ch: str, title: str) -> str:
    return f'<span class="{cls}" title="{html.escape(title)}">{_esc(ch)}</span>'


def render_ops(ops: list[EditOp]) -> tuple[str, str]:
    """对齐序列 → (GT 侧 HTML, 预测侧 HTML)。

    GT 侧：漏提红、错认黄；多提位置不占位（会在预测侧以蓝色出现）。
    预测侧：多提蓝、错认黄；漏提位置不占位。
    两侧都是"插入/删除处不显示占位符"，这样并排看不会错位太多。
    """
    gt_parts: list[str] = []
    pred_parts: list[str] = []
    for op in ops:
        if op.op == "equal":
            gt_parts.append(_esc(op.ref))
            pred_parts.append(_esc(op.hyp))
        elif op.op == "sub":
            gt_parts.append(_span(CLS_SUB, op.ref, f"错认：GT「{op.ref}」→ 预测「{op.hyp}」"))
            pred_parts.append(_span(CLS_SUB, op.hyp, f"错认：GT「{op.ref}」→ 预测「{op.hyp}」"))
        elif op.op == "del":
            gt_parts.append(_span(CLS_DEL, op.ref, "漏提：GT 有这个字，预测未输出"))
        else:  # ins
            pred_parts.append(_span(CLS_INS, op.hyp, "多提：预测多输出了这个字"))
    return "".join(gt_parts), "".join(pred_parts)


def _plain(ops: list[EditOp], side: str) -> str:
    """纯文本版本，用于 CSV / 日志：漏提用〔-x〕、多提用〔+x〕、错认用〔x>y〕。"""
    out: list[str] = []
    for op in ops:
        if op.op == "equal":
            out.append(op.ref if side == "gt" else op.hyp)
        elif op.op == "sub":
            out.append(f"〔{op.ref}>{op.hyp}〕" if side == "gt" else f"〔{op.hyp}〕")
        elif op.op == "del" and side == "gt":
            out.append(f"〔-{op.ref}〕")
        elif op.op == "ins" and side == "pred":
            out.append(f"〔+{op.hyp}〕")
    return "".join(out)


def diff_text(
    gt_text: str | None,
    pred_text: str | None,
    normalize: NormalizeConfig | None = None,
) -> DiffResult:
    """对 GT 与预测做字符级对齐。两侧都先按同一口径归一化，和 CER 口径一致。"""
    cfg = normalize or NormalizeConfig()
    ref = cfg.apply(gt_text)
    hyp = cfg.apply(pred_text)
    ops = align(ref, hyp)
    gt_html, pred_html = render_ops(ops)
    return DiffResult(
        gt_html=gt_html,
        pred_html=pred_html,
        gt_plain=_plain(ops, "gt"),
        pred_plain=_plain(ops, "pred"),
        stats=edit_stats(ref, hyp),
        ops=ops,
    )


def error_counts(gt_text: str | None, pred_text: str | None,
                 normalize: NormalizeConfig | None = None) -> dict[str, int]:
    """字符级绝对计数（报告里的"漏提 12 字"用它，比只看比率直观）。"""
    st = diff_text(gt_text, pred_text, normalize).stats
    return {
        "ref_chars": st.ref_len,
        "hyp_chars": st.hyp_len,
        "sub": st.sub,
        "del": st.delete,
        "ins": st.insert,
        "errors": st.distance,
    }
