"""中文 HTML 报告渲染：单文件、自包含（内联 CSS + base64 缩略图，零外链）。

为什么不用 Jinja 模板文件：报告要能当"证据"直接发给别人，
用代码拼装可以保证任何字段缺失都降级成"—"，不会因为模板变量缺失炸掉。
"""
from __future__ import annotations

from typing import Any, Iterable

from report.format import (
    esc,
    money,
    money_display,
    ms,
    num,
    pct,
    throughput,
)
from report.media import pil_available, thumb_block
from report.render import ReportBundle
from report.stats import EngineStat, SORT_KEYS, SampleRow

CSS = """
:root{--fg:#1f2430;--muted:#6b7280;--line:#e5e7eb;--bg:#ffffff;--soft:#f8fafc;
--del:#b91c1c;--del-bg:#fde2e1;--ins:#1d4ed8;--ins-bg:#dbe7ff;--sub:#92400e;--sub-bg:#fdf0c8;
--ok:#15803d;--warn:#b45309;--bad:#b91c1c;--accent:#0f766e}
*{box-sizing:border-box}
body{margin:0;padding:24px 28px 64px;background:var(--soft);color:var(--fg);
font:14px/1.65 -apple-system,"Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",
"PingFang SC","Hiragino Sans GB",sans-serif}
main{max-width:1500px;margin:0 auto}
h1{font-size:24px;margin:0 0 6px}
h2{font-size:19px;margin:34px 0 12px;padding-left:10px;border-left:4px solid var(--accent)}
h3{font-size:15px;margin:20px 0 8px}
.sub{color:var(--muted);font-size:13px;margin:0 0 18px}
.card{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:16px 18px;
margin-bottom:18px}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:6px 22px;
font-size:13px;margin:0}
.meta div{color:var(--muted)}
.meta b{color:var(--fg);font-weight:600}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0 0}
.kpi{flex:1 1 180px;background:var(--soft);border:1px solid var(--line);border-radius:10px;
padding:10px 14px}
.kpi .k{font-size:12px;color:var(--muted)}
.kpi .v{font-size:19px;font-weight:700;margin-top:2px}
ul.summary{margin:8px 0 0;padding-left:20px}
ul.summary li{margin:3px 0}
table{width:100%;border-collapse:collapse;background:var(--bg);font-size:13px;
border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right;
white-space:nowrap;vertical-align:middle}
th{background:#f1f5f9;font-weight:600;color:#334155;text-align:right;position:relative}
th:first-child,td:first-child,th.l,td.l{text-align:left}
tbody tr:hover{background:#f9fafb}
tbody tr:last-child td{border-bottom:none}
td.best{color:var(--ok);font-weight:700}
td.worst{color:var(--bad)}
.tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;
border:1px solid var(--line);color:var(--muted);background:var(--soft)}
.tag.pareto{border-color:#99f6e4;background:#ccfbf1;color:#0f766e}
.tag.bad{border-color:#fecaca;background:#fee2e2;color:var(--bad)}
.muted{color:var(--muted)}
.nowrap{white-space:nowrap}
.bars{margin:6px 0 0}
.bar-row{display:flex;align-items:center;gap:8px;margin:3px 0;font-size:12px}
.bar-row .lab{width:120px;color:var(--muted);text-align:right;flex:0 0 auto}
.bar{height:13px;background:var(--accent);border-radius:3px;min-width:2px}
.bar-row .val{color:var(--muted);flex:0 0 auto}
details.sample{background:var(--bg);border:1px solid var(--line);border-radius:10px;
margin-bottom:12px;overflow:hidden}
details.sample>summary{cursor:pointer;padding:10px 14px;font-weight:600;
display:flex;gap:14px;align-items:center;flex-wrap:wrap}
details.sample[open]>summary{border-bottom:1px solid var(--line);background:#f8fafc}
.sample-body{padding:14px}
.sample-grid{display:grid;grid-template-columns:minmax(240px,420px) 1fr;gap:18px}
@media (max-width:900px){.sample-grid{grid-template-columns:1fr}}
figure.thumb{margin:0}
figure.thumb img{width:100%;height:auto;border:1px solid var(--line);border-radius:8px;
display:block}
.thumb-cap{font-size:12px;color:var(--muted);margin-top:4px;word-break:break-all}
.thumb-missing{border:1px dashed var(--line);border-radius:8px;padding:36px 10px;
text-align:center;color:var(--muted);background:var(--soft)}
.thumb-missing span{font-size:12px}
.engine-block{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:12px}
.engine-head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.engine-head .name{font-weight:700}
.chips{display:flex;gap:6px;flex-wrap:wrap;font-size:12px;margin-bottom:8px}
.chip{padding:1px 8px;border-radius:6px;background:var(--soft);border:1px solid var(--line);
color:#334155}
.chip.err{background:#fee2e2;border-color:#fecaca;color:var(--bad)}
.pane{border:1px solid var(--line);border-radius:6px;padding:8px 10px;background:#fff;
white-space:pre-wrap;word-break:break-all;font-size:13px;margin-bottom:6px;
font-family:"Noto Sans Mono CJK SC",ui-monospace,Menlo,Consolas,monospace}
.pane .h{font-size:11px;color:var(--muted);margin-bottom:4px;font-family:inherit}
.d-del{background:var(--del-bg);color:var(--del);text-decoration:line-through;
text-decoration-thickness:1px}
.d-ins{background:var(--ins-bg);color:var(--ins)}
.d-sub{background:var(--sub-bg);color:var(--sub);border-bottom:2px dotted #d97706}
.legend{display:flex;gap:16px;font-size:12px;color:var(--muted);flex-wrap:wrap;margin:6px 0 10px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px;
vertical-align:-2px}
.perfect{color:var(--ok);font-size:12px}
footer{margin-top:30px;color:var(--muted);font-size:12px}
code{background:var(--soft);padding:0 4px;border-radius:4px;font-size:12px}
"""


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _best_indexes(values: list[float | None], higher_better: bool) -> set[int]:
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(present) < 2:
        return set()
    target = max(v for _, v in present) if higher_better else min(v for _, v in present)
    return {i for i, v in present if abs(v - target) < 1e-12}


def _cells(values: list[str], best: set[int], cls: str = "") -> str:
    out = []
    for i, v in enumerate(values):
        klass = " ".join(x for x in (cls, "best" if i in best else "") if x)
        out.append(f'<td class="{klass}">{v}</td>' if klass else f"<td>{v}</td>")
    return "".join(out)


def _table(headers: list[str], rows_html: list[str], left_cols: int = 1) -> str:
    head = "".join(
        f'<th class="{"l" if i < left_cols else ""}">{esc(h)}</th>'
        for i, h in enumerate(headers)
    )
    return (
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"
    )


# --------------------------------------------------------------------------
# 各区块
# --------------------------------------------------------------------------
def _header(bundle: ReportBundle) -> str:
    stats = bundle.sample_stats()
    ds = bundle.ctx
    run = bundle.run
    rate = bundle.opts.rate
    env = run.env or {}
    norm = bundle.normalize
    norm_bits = []
    if norm.strip_whitespace:
        norm_bits.append("去空白")
    if norm.unify_punct:
        norm_bits.append("全半角统一(NFKC)")
    if norm.lower:
        norm_bits.append("转小写")
    if norm.drop_punct:
        norm_bits.append("丢标点")
    meta_items = [
        ("数据集", f"{ds.name}（语言 {ds.lang}）"),
        ("样本数", f"{stats['samples']} 个（有标注 {stats['with_gt']} 个）"),
        ("引擎数", f"{stats['engines']} 个"),
        ("结果文件", bundle.run_json or "—"),
        ("运行时间", run.created_at or "—"),
        ("报告生成", bundle.generated_at),
        ("归一化口径", "、".join(norm_bits) or "不归一化"),
        ("汇率", f"1 USD = {rate} CNY"),
        ("准确率口径", bundle.accuracy_label),
        ("总榜排序", SORT_KEYS[bundle.opts.sort][0]),
    ]
    if env:
        bits = " · ".join(f"{k}={v}" for k, v in list(env.items())[:6])
        meta_items.append(("运行环境", bits))
    meta_html = "".join(f"<div>{esc(k)}：<b>{esc(v)}</b></div>" for k, v in meta_items)

    kpis = []
    if bundle.engines:
        best = bundle.engines[0]
        acc = best.value(bundle.opts.accuracy_metric)
        kpis.append(("榜首引擎", esc(best.engine_id)))
        kpis.append((bundle.accuracy_label, pct(acc)))
        kpis.append(("榜首 CER", pct(best.metrics.get("cer"))))
        kpis.append(("榜首每千张成本", money_display(best.per_1000_usd, rate)))
        kpis.append(("样本失败数", str(stats["errors"])))
    kpi_html = "".join(
        f'<div class="kpi"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'
        for k, v in kpis
    )

    summary_lines = "".join(f"<li>{esc(line)}</li>" for line in bundle.summary.get("lines", []))
    return f"""
<h1>{esc(bundle.title)}</h1>
<p class="sub">按 CER / 完整率 / 漏提 / 多提 / 延迟 / 每千张成本排序对比；
所有图片已内嵌为 base64，本文件可离线独立打开，不依赖任何 CDN 或外网资源。</p>
<div class="card">
  <p class="meta">{meta_html}</p>
  <div class="kpis">{kpi_html}</div>
  <h3>选型结论</h3>
  <ul class="summary">{summary_lines or '<li class="muted">无可用的选型结论（数据不足）。</li>'}</ul>
</div>"""


def _leaderboard(bundle: ReportBundle) -> str:
    rate = bundle.opts.rate
    engines = bundle.engines
    headers = [
        "排名", "引擎", "类型", "样本(失败)", "CER ↓", "错认率 ↓", "漏提率 ↓", "多提率 ↓",
        "完整率 ↑", "行级F1 ↑", "定位IoU ↑", "完全匹配 ↑",
        "字符错误(漏/多/错)", "平均延迟 ↓", "P90 延迟 ↓", "吞吐", "每千张成本 ↓", "相邻差值",
    ]
    rows = []
    prev_cer: float | None = None
    for rank, s in enumerate(engines, start=1):
        cer = s.metrics.get("cer")
        if prev_cer is None or cer is None:
            delta = '<span class="muted">—</span>'
        else:
            d = cer - prev_cer
            cls = "best" if d < 0 else ("worst" if d > 0 else "muted")
            delta = f'<span class="{cls}">{d * 100:+.2f}pp</span>'
        prev_cer = cer if cer is not None else prev_cer
        counts = s.counts or {}
        cnt = (
            f"{counts.get('del', 0)}/{counts.get('ins', 0)}/{counts.get('sub', 0)}"
            if counts else "—"
        )
        tags = []
        if s.pareto:
            tags.append('<span class="tag pareto">帕累托</span>')
        if s.note:
            tags.append(f'<span class="tag bad">失败</span>')
        rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f'<td class="l"><b>{esc(s.engine_id)}</b> {" ".join(tags)}</td>'
            f'<td class="l"><span class="tag">{esc(s.engine_type or "—")}</span></td>'
            f'<td>{s.samples_total}({s.samples_error})</td>'
            f"<td>{pct(cer)}</td><td>{pct(s.metrics.get('sub_rate'))}</td>"
            f"<td>{pct(s.metrics.get('del_rate'))}</td><td>{pct(s.metrics.get('ins_rate'))}</td>"
            f"<td>{pct(s.metrics.get('char_recall'))}</td>"
            f"<td>{num(s.metrics.get('line_f1'))}</td>"
            f"<td>{num(s.metrics.get('box_iou_mean'))}</td>"
            f"<td>{pct(s.metrics.get('exact_match'))}</td>"
            f"<td>{cnt}</td>"
            f"<td>{ms(s.latency.get('mean'))}</td><td>{ms(s.latency.get('p90'))}</td>"
            f"<td>{throughput(s.throughput_per_min)}</td>"
            f"<td>{money_display(s.per_1000_usd, rate)}</td>"
            f"<td>{delta}</td>"
            "</tr>"
        )
    note = (
        f'<p class="sub">排序键：{esc(SORT_KEYS[bundle.opts.sort][0])}；'
        "「相邻差值」= 与上一名的 CER 差距（负值表示更准）。"
        "字符错误列为「漏提/多提/错认」的绝对字数，比率会被长文本稀释，看绝对数更能定位问题。</p>"
    )
    return note + _table(headers, rows, left_cols=2)


def _scene_section(bundle: ReportBundle) -> str:
    if not bundle.scenes:
        return '<p class="muted">数据集缺少场景标签，未做分场景分组。</p>'
    rate = bundle.opts.rate
    headers = [
        "引擎", "样本", "CER ↓", "完整率 ↑", "漏提率 ↓", "多提率 ↓",
        "行级F1 ↑", "平均延迟 ↓", "每千张成本 ↓",
    ]
    blocks = []
    for scene, stats in bundle.scenes.items():
        rows = []
        for s in stats:
            rows.append(
                "<tr>"
                f'<td class="l"><b>{esc(s.engine_id)}</b></td>'
                f"<td>{s.samples_ok}/{s.samples_total}</td>"
                f"<td>{pct(s.metrics.get('cer'))}</td>"
                f"<td>{pct(s.metrics.get('char_recall'))}</td>"
                f"<td>{pct(s.metrics.get('del_rate'))}</td>"
                f"<td>{pct(s.metrics.get('ins_rate'))}</td>"
                f"<td>{num(s.metrics.get('line_f1'))}</td>"
                f"<td>{ms(s.latency.get('mean'))}</td>"
                f"<td>{money_display(s.per_1000_usd, rate)}</td>"
                "</tr>"
            )
        blocks.append(f"<h3>场景：{esc(scene)}</h3>" + _table(headers, rows, left_cols=1))
    return "".join(blocks)


def _latency_section(bundle: ReportBundle) -> str:
    rows_data = bundle.latency_table()
    headers = ["引擎", "有效样本", "平均 ↓", "P50 ↓", "P90 ↓", "P99 ↓", "最大", "吞吐"]
    rows = []
    for r in rows_data:
        rows.append(
            "<tr>"
            f'<td class="l"><b>{esc(r["engine_id"])}</b></td>'
            f'<td>{r["n"]}</td><td>{ms(r["mean"])}</td><td>{ms(r["p50"])}</td>'
            f'<td>{ms(r["p90"])}</td><td>{ms(r["p99"])}</td><td>{ms(r["max"])}</td>'
            f'<td>{throughput(r["throughput"])}</td>'
            "</tr>"
        )
    table = _table(headers, rows, left_cols=1)

    charts = []
    for r in rows_data:
        hist = r["hist"]
        if not hist:
            charts.append(
                f'<h3>{esc(r["engine_id"])}</h3><p class="muted">无有效延迟样本（全部失败或全部命中缓存）。</p>'
            )
            continue
        peak = max(c for _, c, _ in hist) or 1
        bars = "".join(
            f'<div class="bar-row"><span class="lab">{esc(label)}</span>'
            f'<span class="bar" style="width:{max(2, int(count / peak * 360))}px"></span>'
            f'<span class="val">{count} 次（{share * 100:.0f}%）</span></div>'
            for label, count, share in hist
        )
        charts.append(f'<h3>{esc(r["engine_id"])} 延迟分布</h3><div class="bars">{bars}</div>')
    note = (
        '<p class="sub">缓存命中样本不计入延迟与成本（否则数字会假性变好）；'
        "P99 在样本数 < 100 时仅供参考，压测请把 <code>repeats</code> 调到 3 以上。</p>"
    )
    return note + table + "".join(charts)


def _cost_section(bundle: ReportBundle) -> str:
    rate = bundle.opts.rate
    label = bundle.accuracy_label
    rows_data = bundle.cost_table()
    headers = [
        "引擎", "单张成本", "每千张成本(USD)", "每千张成本(CNY)",
        "每千分钟成本(USD)", "每千分钟成本(CNY)", f"{label} ↑",
        "每提升 1pp 成本(USD/千张)", "选型建议",
    ]
    rows = []
    for r in rows_data:
        accs = [x["accuracy"] for x in rows_data]
        best = _best_indexes(accs, higher_better=True)
        idx = rows_data.index(r)
        advice = []
        if r["pareto"]:
            advice.append('<span class="tag pareto">帕累托前沿</span>')
        if r["marginal_per_pp_usd"] is None:
            advice.append('<span class="tag">基准/无精度优势</span>')
        if r["note"]:
            advice.append(f'<span class="tag bad">{esc(r["note"])}</span>')
        rows.append(
            "<tr>"
            f'<td class="l"><b>{esc(r["engine_id"])}</b></td>'
            f'<td>{money(r["cost_mean_usd"], 6)}</td>'
            f'<td>{money(r["per_1000_usd"])}</td>'
            f'<td>{money(r["per_1000_cny"])}</td>'
            f'<td>{money(r["per_1000_min_usd"])}</td>'
            f'<td>{money(r["per_1000_min_cny"])}</td>'
            f'<td class="{"best" if idx in best else ""}">{pct(r["accuracy"])}</td>'
            f'<td>{money(r["marginal_per_pp_usd"])}</td>'
            f'<td class="l">{" ".join(advice) or "—"}</td>'
            "</tr>"
        )
    note = (
        f'<p class="sub">每千分钟成本 = 单张成本 ÷ 单张机时(分钟) × 1000，用于对比"同样机时预算下"的产出成本；'
        f'「每提升 1pp 成本」以最便宜引擎为基线：Δ每千张成本 ÷ Δ{label}百分点，'
        "数值越大说明为精度花的钱越不划算。汇率 1 USD = "
        f"{rate} CNY（<code>--rate</code> 可改）。</p>"
    )
    return note + _table(headers, rows, left_cols=1)


def _sample_section(bundle: ReportBundle) -> str:
    if not bundle.samples:
        return '<p class="muted">没有可展示的样本。</p>'
    legend = "".join(
        f'<span><i style="background:var(--{c})"></i>{esc(t)}</span>'
        for c, t in (
            ("del-bg", "漏提：GT 有、预测无"),
            ("ins-bg", "多提：预测多出"),
            ("sub-bg", "错认：认成了别的字"),
        )
    )
    blocks = []
    for row in bundle.samples:
        blocks.append(_sample_block(bundle, row))
    note = (
        '<p class="sub">逐样本对照按 原图 | GT | 各引擎预测 展开，字符级 diff 用下方配色；'
        "diff 与 CER 使用同一套归一化口径（见页首「归一化口径」）。</p>"
    )
    return note + f'<div class="legend">{legend}</div>' + "".join(blocks)


def _sample_block(bundle: ReportBundle, row: SampleRow) -> str:
    rate = bundle.opts.rate
    cer_bits = []
    for engine_id, cell in row.cells.items():
        if cell.metrics.cer is not None:
            cer_bits.append(f"{engine_id} {cell.metrics.cer * 100:.2f}%")
        elif not cell.ok:
            cer_bits.append(f"{engine_id} 失败")
    summary_bits = " · ".join(cer_bits) or "无指标"
    thumb = (
        thumb_block(row.media, caption=row.sample_id, max_px=bundle.opts.thumb_px)
        if bundle.opts.include_images
        else '<div class="thumb-missing">已关闭图片内嵌<br><span>（--no-images）</span></div>'
    )

    engines_html = []
    if row.gt_text is not None:
        gt_pane = (
            f'<div class="pane"><div class="h">GT 标注（错认黄 / 漏提红）</div>'
            f'{esc(row.gt_text) if not row.cells else _gt_diff_pane(row)}</div>'
        )
        engines_html.append(gt_pane)
    else:
        engines_html.append(
            '<div class="pane"><div class="h">GT 标注</div>'
            '<span class="muted">该样本没有标注，不参与 CER 计算</span></div>'
        )

    for engine_id in bundle.engine_ids:
        cell = row.cells.get(engine_id)
        if cell is None:
            engines_html.append(
                f'<div class="engine-block"><div class="engine-head">'
                f'<span class="name">{esc(engine_id)}</span>'
                '<span class="muted">本次运行未覆盖该样本</span></div></div>'
            )
            continue
        sm = cell.metrics
        chips = [
            f'<span class="chip">CER {pct(sm.cer)}</span>',
            f'<span class="chip">完整率 {pct(sm.char_recall)}</span>',
            f'<span class="chip">漏提 {pct(sm.del_rate)}</span>',
            f'<span class="chip">多提 {pct(sm.ins_rate)}</span>',
            f'<span class="chip">错认 {pct(sm.sub_rate)}</span>',
            f'<span class="chip">延迟 {ms(sm.latency_ms)}</span>',
            f'<span class="chip">成本 {money(sm.cost_usd, 6)} (¥{sm.cost_usd * rate:,.6f})</span>',
        ]
        if sm.line_f1 is not None:
            chips.append(f'<span class="chip">行F1 {num(sm.line_f1)}</span>')
        if sm.box_iou_mean is not None:
            chips.append(f'<span class="chip">定位IoU {num(sm.box_iou_mean)}</span>')
        if cell.prediction.error:
            chips.append(f'<span class="chip err">失败：{esc(cell.prediction.error)}</span>')

        if cell.prediction.error:
            body = (
                f'<div class="pane"><div class="h">预测</div>'
                f'<span class="err">{esc(cell.prediction.error)}</span></div>'
            )
        elif cell.diff is not None:
            perfect = '<span class="perfect">✔ 与 GT 完全一致</span>' if cell.diff.is_perfect else ""
            body = (
                f'<div class="pane"><div class="h">预测转录（多提蓝 / 错认黄）{perfect}</div>'
                f"{cell.diff.pred_html or '<span class=muted>（空输出）</span>'}</div>"
            )
            st = cell.diff.stats
            body += (
                f'<div class="muted" style="font-size:12px">GT {st.ref_len} 字 / '
                f"预测 {st.hyp_len} 字 · 漏提 {st.delete} · 多提 {st.insert} · "
                f"错认 {st.sub} · 编辑距离 {st.distance}</div>"
            )
        else:
            body = (
                f'<div class="pane"><div class="h">预测转录</div>'
                f"{esc(cell.text) or '<span class=muted>（空输出）</span>'}</div>"
            )
        engines_html.append(
            f'<div class="engine-block"><div class="engine-head">'
            f'<span class="name">{esc(engine_id)}</span></div>'
            f'<div class="chips">{"".join(chips)}</div>{body}</div>'
        )

    return (
        f'<details class="sample"><summary>'
        f'<span>{esc(row.sample_id)}</span>'
        f'<span class="tag">{esc(row.scene)}</span>'
        f'<span class="muted" style="font-weight:400">{esc(summary_bits)}</span>'
        "</summary>"
        '<div class="sample-body"><div class="sample-grid">'
        f'<div>{thumb}</div><div>{"".join(engines_html)}</div>'
        "</div></div></details>"
    )


def _gt_diff_pane(row: SampleRow) -> str:
    """GT 侧高亮：优先用第一个有 diff 的引擎的口径（口径相同，取任一即可）。"""
    for cell in row.cells.values():
        if cell.diff is not None:
            return cell.diff.gt_html or esc(row.gt_text or "")
    return esc(row.gt_text or "")


def _appendix(bundle: ReportBundle) -> str:
    ds_meta = bundle.ctx.meta or {}
    meta_rows = "".join(
        f"<tr><td class='l'>{esc(k)}</td><td class='l'>{esc(v)}</td></tr>"
        for k, v in ds_meta.items()
    )
    env_rows = "".join(
        f"<tr><td class='l'>{esc(k)}</td><td class='l'>{esc(v)}</td></tr>"
        for k, v in (bundle.run.env or {}).items()
    )
    engine_rows = "".join(
        "<tr>"
        f'<td class="l"><b>{esc(s.engine_id)}</b></td>'
        f'<td class="l">{esc(s.engine_type or "—")}</td>'
        f'<td class="l">{esc(_safe_params(bundle, s.engine_id))}</td>'
        "</tr>"
        for s in bundle.engines
    )
    img_note = (
        "缩略图已转 base64 内嵌（最长边 "
        f"{bundle.opts.thumb_px}px、JPEG 质量 72），报告不含任何外链。"
        if pil_available() and bundle.opts.include_images
        else "本次未内嵌图片（Pillow 不可用或已用 --no-images 关闭）。"
    )
    return f"""
<h2>引擎配置与可复现信息</h2>
<div class="card">
{_table(["引擎", "类型", "参数（凭证已隐藏）"], [engine_rows], left_cols=3) if engine_rows else '<p class="muted">无引擎配置。</p>'}
</div>
<h2>附录：数据集元信息 / 运行环境 / 指标口径</h2>
<div class="card">
<h3>数据集 meta.yaml</h3>
{_table(["键", "值"], [meta_rows], left_cols=2) if meta_rows else '<p class="muted">数据集未提供 meta.yaml。</p>'}
<h3>运行环境</h3>
{_table(["项", "值"], [env_rows], left_cols=2) if env_rows else '<p class="muted">run.json 未记录环境信息。</p>'}
<h3>指标口径</h3>
<ul class="summary">
<li><b>CER</b> = (错认 + 漏提 + 多提) / GT 字数，按字符级编辑距离拆解，越低越好。</li>
<li><b>完整率</b> = 1 − 漏提率 − 错认率，直接对应"文字尽可能提全"的业务目标。</li>
<li><b>漏提率</b>：GT 有、预测没有的字；传统 OCR 常见错误。</li>
<li><b>多提率</b>：预测多出的字；大模型幻觉的典型表现。</li>
<li><b>错认率</b>：GT 有这个字但被认成别的字。</li>
<li><b>行级 F1</b>：按归一化后的行文本集合匹配，免疫行序差异。</li>
<li><b>定位 IoU</b>：仅在 GT 有 box 且引擎输出 box 时计算，区分"真读到"与"猜到内容"。</li>
<li><b>完全匹配</b>：整段文本与 GT 完全一致的样本占比。</li>
<li><b>成本</b>：run.json 内成本为 USD，报告按 {bundle.opts.rate} 汇率折算人民币。</li>
</ul>
<p class="sub">{esc(img_note)}</p>
</div>
"""


def _safe_params(bundle: ReportBundle, engine_id: str) -> str:
    """展示引擎参数，但隐去可能存在的 base_url / 凭证 —— 报告要能外发。"""
    for cfg in (bundle.run.config or {}).get("engines") or []:
        if (cfg.get("id") or cfg.get("type")) != engine_id:
            continue
        params = cfg.get("params") or {}
        bits = []
        for k, v in params.items():
            kl = str(k).lower()
            if any(s in kl for s in ("key", "secret", "token", "password", "url", "endpoint")):
                bits.append(f"{k}=***")
            else:
                bits.append(f"{k}={v}")
        cost = cfg.get("cost") or {}
        if cost:
            bits.append("cost=" + ",".join(f"{k}:{v}" for k, v in cost.items()))
        return "; ".join(bits) or "—"
    return "—"


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def render_html(bundle: ReportBundle) -> str:
    """渲染完整的中文自包含 HTML 报告。"""
    body = "".join([
        _header(bundle),
        "<h2>引擎总榜</h2>",
        _leaderboard(bundle),
        "<h2>分场景分组</h2>",
        _scene_section(bundle),
        "<h2>延迟分布</h2>",
        _latency_section(bundle),
        "<h2>成本核算（每千张 / 每千分钟 / 边际成本）</h2>",
        _cost_section(bundle),
        "<h2>逐样本对照（原图 | GT | 各引擎预测 + 字符级 diff）</h2>",
        _sample_section(bundle),
        _appendix(bundle),
    ])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(bundle.title)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
{body}
<footer>本报告由 veval report 生成 · {esc(bundle.generated_at)} · 数据源 {esc(bundle.run_json or bundle.run.run_name)}</footer>
</main>
</body>
</html>
"""
