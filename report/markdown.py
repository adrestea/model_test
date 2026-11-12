"""Markdown 报告：便于贴进 PR / 内部文档 / issue 的版本。

与 HTML 同源同数据（都从 ReportBundle 渲染），差别只在排版：
表格用 GFM 管道表，diff 用行内 <span style>（GitHub/GitLab 均可渲染）。
"""
from __future__ import annotations

import re
from typing import Any

from report.format import esc, money, money_display, ms, num, pct, throughput
from report.render import ReportBundle
from report.stats import SORT_KEYS

# HTML 类名 → 行内样式（Markdown 环境里拿不到报告自己的 CSS）
_INLINE_STYLE = {
    "d-del": "background:#fde2e1;color:#b91c1c;text-decoration:line-through",
    "d-ins": "background:#dbe7ff;color:#1d4ed8",
    "d-sub": "background:#fdf0c8;color:#92400e;border-bottom:2px dotted #d97706",
}


def _inline(html_str: str) -> str:
    """把 class 换成 style，并去掉 title（Markdown 里 title 只会变成噪声）。"""
    out = re.sub(r'\s*title="[^"]*"', "", html_str)
    for cls, style in _INLINE_STYLE.items():
        out = out.replace(f'class="{cls}"', f'style="{style}"')
    return out


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_table(headers: list[str], rows: list[list[Any]], align_right_from: int = 1) -> str:
    head = "| " + " | ".join(_cell(h) for h in headers) + " |"
    sep_cells = []
    for i, _ in enumerate(headers):
        sep_cells.append("---:" if i >= align_right_from else ":---")
    sep = "| " + " | ".join(sep_cells) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return "\n".join([head, sep, *body])


def render_markdown(bundle: ReportBundle) -> str:
    rate = bundle.opts.rate
    stats = bundle.sample_stats()
    out: list[str] = [f"# {bundle.title}", ""]

    out.append(
        f"- 数据集：**{bundle.ctx.name}**（语言 {bundle.ctx.lang}） · "
        f"样本 {stats['samples']} 个（有标注 {stats['with_gt']} 个） · "
        f"引擎 {stats['engines']} 个 · 预测 {stats['predictions']} 条"
    )
    out.append(f"- 结果文件：`{bundle.run_json or bundle.run.run_name}`")
    out.append(f"- 运行时间：{bundle.run.created_at or '—'} · 报告生成：{bundle.generated_at}")
    out.append(
        f"- 准确率口径：**{bundle.accuracy_label}** · 总榜排序：**{SORT_KEYS[bundle.opts.sort][0]}** · "
        f"汇率：1 USD = {rate} CNY"
    )
    out.append("")

    out.append("## 选型结论")
    out.append("")
    for line in bundle.summary.get("lines", []):
        out.append(f"- {line}")
    if not bundle.summary.get("lines"):
        out.append("- 数据不足，无法给出结论。")
    out.append("")

    out.append("## 引擎总榜")
    out.append("")
    headers = [
        "排名", "引擎", "类型", "样本(失败)", "CER↓", "错认率↓", "漏提率↓", "多提率↓",
        "完整率↑", "行级F1↑", "定位IoU↑", "完全匹配↑", "漏/多/错字数",
        "平均延迟↓", "P90↓", "吞吐", "每千张成本↓",
    ]
    rows = []
    for i, s in enumerate(bundle.engines, start=1):
        c = s.counts or {}
        counts = f"{c.get('del', 0)}/{c.get('ins', 0)}/{c.get('sub', 0)}" if c else "—"
        name = s.engine_id + (" ✅帕累托" if s.pareto else "")
        rows.append([
            i, name, s.engine_type or "—", f"{s.samples_total}({s.samples_error})",
            pct(s.metrics.get("cer")), pct(s.metrics.get("sub_rate")),
            pct(s.metrics.get("del_rate")), pct(s.metrics.get("ins_rate")),
            pct(s.metrics.get("char_recall")), num(s.metrics.get("line_f1")),
            num(s.metrics.get("box_iou_mean")), pct(s.metrics.get("exact_match")),
            counts, ms(s.latency.get("mean")), ms(s.latency.get("p90")),
            throughput(s.throughput_per_min), money_display(s.per_1000_usd, rate),
        ])
    out.append(_md_table(headers, rows, align_right_from=3))
    out.append("")

    out.append("## 分场景分组")
    out.append("")
    if not bundle.scenes:
        out.append("数据集缺少场景标签，未做分场景分组。")
    for scene, engines in bundle.scenes.items():
        out.append(f"### 场景：{scene}")
        out.append("")
        rows = []
        for s in engines:
            rows.append([
                s.engine_id, f"{s.samples_ok}/{s.samples_total}",
                pct(s.metrics.get("cer")), pct(s.metrics.get("char_recall")),
                pct(s.metrics.get("del_rate")), pct(s.metrics.get("ins_rate")),
                num(s.metrics.get("line_f1")), ms(s.latency.get("mean")),
                money_display(s.per_1000_usd, rate),
            ])
        out.append(_md_table(
            ["引擎", "样本", "CER↓", "完整率↑", "漏提率↓", "多提率↓", "行级F1↑", "平均延迟↓", "每千张成本↓"],
            rows, align_right_from=1,
        ))
        out.append("")

    out.append("## 延迟分布")
    out.append("")
    rows = []
    for r in bundle.latency_table():
        rows.append([
            r["engine_id"], r["n"], ms(r["mean"]), ms(r["p50"]), ms(r["p90"]),
            ms(r["p99"]), ms(r["max"]), throughput(r["throughput"]),
        ])
    out.append(_md_table(
        ["引擎", "有效样本", "平均↓", "P50↓", "P90↓", "P99↓", "最大", "吞吐"],
        rows, align_right_from=1,
    ))
    out.append("")
    out.append("> 缓存命中样本不计入延迟/成本；样本数 < 100 时 P99 仅供参考。")
    out.append("")

    out.append("## 成本核算")
    out.append("")
    rows = []
    for r in bundle.cost_table():
        rows.append([
            r["engine_id"], money(r["cost_mean_usd"], 6),
            money(r["per_1000_usd"]), money(r["per_1000_cny"]),
            money(r["per_1000_min_usd"]), money(r["per_1000_min_cny"]),
            pct(r["accuracy"]), money(r["marginal_per_pp_usd"]),
            "帕累托" if r["pareto"] else "—",
        ])
    out.append(_md_table(
        ["引擎", "单张成本", "每千张(USD)", "每千张(CNY)", "每千分钟(USD)",
         "每千分钟(CNY)", f"{bundle.accuracy_label}↑", "每提升1pp成本(USD/千张)", "选型"],
        rows, align_right_from=1,
    ))
    out.append("")
    out.append(
        f"> 每千分钟成本 = 单张成本 ÷ 单张机时(分钟) × 1000；"
        f"「每提升 1pp 成本」以最便宜引擎为基线（Δ成本 ÷ Δ{bundle.accuracy_label}百分点）。"
    )
    out.append("")

    out.append("## 逐样本对照")
    out.append("")
    out.append("配色：<span style=\"background:#fde2e1;color:#b91c1c\">漏提</span> · "
               "<span style=\"background:#dbe7ff;color:#1d4ed8\">多提</span> · "
               "<span style=\"background:#fdf0c8;color:#92400e\">错认</span>")
    out.append("")
    for row in bundle.samples:
        out.append(f"### 样本 `{row.sample_id}`（场景：{row.scene}）")
        out.append("")
        if row.media:
            out.append(f"原图：`{row.media}`")
            out.append("")
        if row.gt_text is not None:
            gt_html = None
            for cell in row.cells.values():
                if cell.diff is not None:
                    gt_html = cell.diff.gt_html
                    break
            out.append(f"**GT**：{_inline(gt_html) if gt_html is not None else _cell(row.gt_text)}")
            out.append("")
        else:
            out.append("**GT**：该样本无标注，不参与 CER 计算")
            out.append("")
        rows = []
        for engine_id, cell in row.cells.items():
            sm = cell.metrics
            pred = cell.prediction
            if pred.error:
                text = f"⚠️ 失败：{pred.error}"
            elif cell.diff is not None:
                text = _inline(cell.diff.pred_html) or "（空输出）"
            else:
                text = _cell(pred.text) or "（空输出）"
            rows.append([
                engine_id, pct(sm.cer), pct(sm.char_recall),
                pct(sm.del_rate), pct(sm.ins_rate), pct(sm.sub_rate),
                ms(sm.latency_ms), money(sm.cost_usd, 6), text,
            ])
        out.append(_md_table(
            ["引擎", "CER", "完整率", "漏提", "多提", "错认", "延迟", "成本(USD)", "预测（diff 高亮）"],
            rows, align_right_from=1,
        ))
        out.append("")

    out.append("## 指标口径")
    out.append("")
    out += [
        "- **CER** = (错认 + 漏提 + 多提) / GT 字数，按字符级编辑距离拆解，越低越好。",
        "- **完整率** = 1 − 漏提率 − 错认率，对应“文字尽可能提全”的业务目标。",
        "- **漏提率** / **多提率** / **错认率** 分别对应 OCR 老毛病与大模型幻觉。",
        "- **行级 F1** 按归一化行文本集合匹配，免疫行序差异；**定位 IoU** 只在有 box 时计算。",
        f"- 成本在 run.json 内为 USD，本文按 1 USD = {rate} CNY 折算。",
        "",
    ]
    return "\n".join(out) + "\n"
