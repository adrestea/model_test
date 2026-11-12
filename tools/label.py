"""标注工具：引擎草稿（draft）+ 本地 HTML 校正页（review）。

工作流（对应 datasets/README.md 的"没有标注怎么办"）：
  1. veval label draft <ds> --engine ocr.rapidocr
     用指定引擎跑一遍数据集，把识别结果落成可编辑的 labels/<id>.json 草稿。
  2. veval label review <ds>
     生成一个自包含 HTML（图片 base64 内嵌、无任何外链），浏览器里改文本/box，
     纯前端导出标准 L2 标注 JSON，拷回 labels/ 即完成 GT。
"""
from __future__ import annotations

import base64
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from core.dataset import IMAGE_EXTS
from core.types import Box, EngineRequest
from tools.inspect import resolve_dataset_root

# 图片扩展名 → data URI 的 mime 类型
_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".bmp": "image/bmp", ".webp": "image/webp", ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


# ==========================================================================
# label draft：引擎识别 → 草稿 GT
# ==========================================================================
def resolve_engine_spec(
    config: str | Path | None = None,
    engine_id: str | None = None,
    engine: str | None = None,
    params: str | None = None,
) -> dict[str, Any]:
    """解析引擎配置，三种来源（CLI 参数一一对应）：
      -c <config> --engine-id <id>：从评测配置里挑一个引擎
      --engine '{"type": "...", "params": {...}}'：完整 JSON spec
      --engine <type> --params '{"k": "v"}'：类型 + 参数
    """
    sources = sum(x is not None for x in (config, engine))
    if sources == 0:
        raise ValueError(
            "需要指定引擎：--engine <类型或JSON> 或 -c <配置> --engine-id <id>"
        )
    if sources > 1:
        raise ValueError("--engine 与 -c/--engine-id 只能二选一")

    if config:
        from core.config import load_config

        cfg = load_config(config)
        engines = list(cfg.engines)
        if engine_id:
            picked = [e for e in engines if (e.get("id") or e.get("type")) == engine_id]
            if not picked:
                raise ValueError(
                    f"配置里没有引擎 {engine_id}；可选: "
                    f"{sorted(e.get('id') or e.get('type') for e in engines)}"
                )
            return dict(picked[0])
        if len(engines) == 1:
            return dict(engines[0])
        raise ValueError(
            "配置里有多个引擎，请用 --engine-id 指定："
            f"{sorted(e.get('id') or e.get('type') for e in engines)}"
        )

    spec_str = engine or ""
    if spec_str.strip().startswith("{"):
        try:
            spec = json.loads(spec_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"--engine JSON 解析失败: {e}") from e
        if not isinstance(spec, dict) or not spec.get("type"):
            raise ValueError('--engine JSON 必须是含 "type" 字段的对象')
    else:
        spec = {"type": spec_str.strip()}
    if params:
        try:
            spec["params"] = {**(spec.get("params") or {}), **json.loads(params)}
        except json.JSONDecodeError as e:
            raise ValueError(f"--params JSON 解析失败: {e}") from e
    spec.setdefault("id", spec.get("type"))
    _check_registered(spec)
    return spec


def _check_registered(spec: dict[str, Any]) -> None:
    """提前校验引擎类型已注册，避免跑完 N 张图才在构建时爆错。"""
    from adapters.base import ENGINE_REGISTRY, load_builtin_adapters

    load_builtin_adapters()
    tname = spec["type"]
    if tname not in ENGINE_REGISTRY:
        raise ValueError(
            f"未注册的引擎类型: {tname}；可选: {sorted(ENGINE_REGISTRY)}"
        )


def _draft_label(pred, image_name: str) -> dict[str, Any] | None:
    """把引擎输出变成标准 L2 草稿标注；完全没内容时返回 None。"""
    lines: list[dict[str, Any]] = []
    if pred.lines:
        for l in pred.lines:
            if not l.text:
                continue
            item: dict[str, Any] = {"text": l.text}
            if l.box is not None:
                item["box"] = [round(v, 1) for v in l.box.to_list()]
            lines.append(item)
    if not lines and pred.text:
        # 引擎只给全文时按换行拆行，box 留空待人工补
        lines = [{"text": t} for t in pred.text.splitlines() if t.strip()]
    if not lines:
        return None
    return {
        "text": "\n".join(l["text"] for l in lines),
        "lines": lines,
        "meta": {
            "draft": True,
            "engine": pred.engine_id,
            "drafted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_image": image_name,
        },
    }


def draft_labels(
    dataset: str,
    spec: dict[str, Any],
    root: str | Path = "datasets",
    overwrite: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """用引擎给数据集生成草稿 GT，写入 labels/<id>.json（已有标注默认跳过）。"""
    from adapters.base import build_engine

    ds_root = resolve_dataset_root(dataset, root)
    images_dir = ds_root / "images"
    labels_dir = ds_root / "labels"
    if not images_dir.is_dir():
        raise FileNotFoundError(f"数据集缺少 images/ 目录: {ds_root}")
    labels_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        p for p in images_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if limit is not None:
        if limit < 0:
            raise ValueError("--limit 不能为负数")
        images = images[:limit]
    if not images:
        raise RuntimeError(f"数据集 {ds_root.name} 没有图片样本")

    engine = build_engine(spec)
    try:
        engine.warmup()  # 预加载模型，不计入任何统计（draft 不测延迟）
    except Exception:  # noqa: BLE001 - warmup 失败不阻断，predict 时再暴露
        pass

    written: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    for path in images:
        sid = path.stem
        label_path = labels_dir / f"{sid}.json"
        if label_path.is_file() and not overwrite:
            skipped.append(sid)
            continue
        req = engine.build_request(
            EngineRequest(
                sample_id=sid, task="recognize", modality="image",
                media_path=str(path),
            )
        )
        pred = engine.predict(req)
        if pred.error is not None:
            failed.append({"sample_id": sid, "error": pred.error})
            continue
        label = _draft_label(pred, path.name)
        if label is None:
            failed.append({"sample_id": sid, "error": "引擎输出为空，无法生成草稿"})
            continue
        label_path.write_text(
            json.dumps(label, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        written.append(sid)

    return {
        "dataset": ds_root.name,
        "labels_dir": labels_dir,
        "engine_id": engine.engine_id,
        "engine_type": engine.type_name,
        "samples": len(images),
        "written": written,
        "skipped": skipped,
        "failed": failed,
    }


# ==========================================================================
# label review：本地 HTML 校正页（自包含、无外链、纯前端导出）
# ==========================================================================
def _normalize_lines(payload: dict) -> list[dict[str, Any]]:
    """把已有标注规范成 [{"text": str, "box": [x1,y1,x2,y2] | None}]。"""
    out: list[dict[str, Any]] = []
    for it in payload.get("lines") or []:
        text = str(it.get("text") or it.get("transcription") or "")
        box = Box.from_any(it.get("box") or it.get("bbox") or it.get("points"))
        out.append({
            "text": text,
            "box": [round(v, 1) for v in box.to_list()] if box else None,
        })
    if not out and payload.get("text"):
        out = [{"text": t, "box": None} for t in str(payload["text"]).splitlines() if t]
    return out


def _load_label_state(sid: str, labels_dir: Path) -> dict[str, Any]:
    """读取单样本标注 → 页面初始状态。没有标注的样本给空行列表。"""
    js = labels_dir / f"{sid}.json"
    txt = labels_dir / f"{sid}.txt"
    if js.is_file():
        payload = json.loads(js.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {"lines": payload} if isinstance(payload, list) else {}
        return {
            "had_label": True,
            "lines": _normalize_lines(payload),
            "fields": payload.get("fields") or None,
            "meta": payload.get("meta") or {},
        }
    if txt.is_file():
        text = txt.read_text(encoding="utf-8")
        return {
            "had_label": True,
            "lines": [{"text": t, "box": None} for t in text.splitlines() if t],
            "fields": None,
            "meta": {"source": "L1纯文本标注"},
        }
    return {"had_label": False, "lines": [], "fields": None, "meta": {}}


def _data_uri(path: Path) -> str:
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_review_page(
    dataset: str,
    root: str | Path = "datasets",
    out: str | Path | None = None,
    title: str | None = None,
) -> Path:
    """生成本地校正页。图片以 base64 内嵌，页面零外链，断网可用。"""
    ds_root = resolve_dataset_root(dataset, root)
    images_dir = ds_root / "images"
    labels_dir = ds_root / "labels"
    if not images_dir.is_dir():
        raise FileNotFoundError(f"数据集缺少 images/ 目录: {ds_root}")

    samples: list[dict[str, Any]] = []
    for path in sorted(images_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        state = _load_label_state(path.stem, labels_dir)
        samples.append({
            "id": path.stem,
            "filename": path.name,
            "data": _data_uri(path),
            "label_path": f"labels/{path.stem}.json",
            **state,
        })
    if not samples:
        raise RuntimeError(f"数据集 {ds_root.name} 没有图片样本")

    payload = {
        "dataset": ds_root.name,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "title": title or f"{ds_root.name} 标注校正页",
        "samples": samples,
    }
    # 防止 JSON 里出现 "</script>" 截断标签
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    out_path = Path(out) if out else Path("results/label_review") / f"{ds_root.name}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_page_html(blob), encoding="utf-8")
    return out_path


def _page_html(data_blob: str) -> str:
    """页面模板：CSS/JS 全内联，导出逻辑纯前端（Blob 下载）。"""
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>veval 标注校正</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 14px/1.6 -apple-system, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
         background: #f2f4f7; color: #1c2330; }}
  header {{ position: sticky; top: 0; z-index: 10; background: #ffffffee;
           border-bottom: 1px solid #d8dee8; padding: 10px 18px; backdrop-filter: blur(6px); }}
  header h1 {{ font-size: 17px; margin: 0 0 4px; }}
  header .tips {{ color: #5a6577; font-size: 12px; max-width: 1000px; }}
  header button {{ margin-left: 10px; }}
  .card {{ background: #fff; border: 1px solid #d8dee8; border-radius: 10px;
          margin: 18px; padding: 14px; max-width: 1080px; }}
  .card-head {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline;
               border-bottom: 1px solid #e8ecf3; padding-bottom: 8px; margin-bottom: 10px; }}
  .card-head .sid {{ font-weight: 700; font-size: 15px; }}
  .card-head .tag {{ font-size: 12px; color: #7a8699; }}
  .badge {{ font-size: 11px; padding: 1px 8px; border-radius: 999px; }}
  .badge.draft {{ background: #fff4e0; color: #a05a00; }}
  .badge.gt {{ background: #e2f6e4; color: #1c6b2d; }}
  .badge.none {{ background: #fdeaea; color: #b02a2a; }}
  .stage {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .imgbox {{ position: relative; flex: 1 1 420px; max-width: 620px; }}
  .imgbox img {{ width: 100%; display: block; border: 1px solid #c9d2e0; background: #fff; }}
  .imgbox svg {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }}
  .imgbox rect {{ fill: rgba(28,110,210,.12); stroke: #1c6ed2; stroke-width: 2; }}
  .editor {{ flex: 1 1 380px; min-width: 340px; }}
  .row {{ display: flex; gap: 6px; margin-bottom: 6px; align-items: center; }}
  .row .no {{ width: 26px; color: #8a93a5; font-size: 12px; text-align: right; }}
  .row input[type=text] {{ flex: 1; min-width: 150px; }}
  .row input[type=number] {{ width: 64px; }}
  .row button {{ padding: 2px 9px; }}
  button {{ font: inherit; border: 1px solid #b9c3d3; background: #fff; color: #1c2330;
           border-radius: 6px; padding: 4px 12px; cursor: pointer; }}
  button:hover {{ background: #eef2f8; }}
  button.primary {{ background: #1c6ed2; border-color: #1c6ed2; color: #fff; }}
  button.primary:hover {{ background: #1558b0; }}
  .empty {{ color: #98a2b3; font-size: 12px; margin: 4px 0; }}
  footer {{ text-align: center; color: #98a2b3; font-size: 12px; padding: 24px; }}
</style>
</head>
<body>
<header>
  <h1 id="title"></h1>
  <div class="tips">
    逐样本核对：<b>文本框</b>改内容，<b>x1/y1/x2/y2</b>改像素框（蓝色覆盖层实时预览）；
    「＋添加一行」可补行（box 可留空）；确认后点「下载 labels/&lt;id&gt;.json」，
    把下载的文件拷进数据集 <code>labels/</code> 目录即完成标注。
    「导出全部」会下载一个 {{sample_id: 标注}} 的汇总 JSON，便于批量保存。
    <span style="color:#b02a2a">页面关闭前请先下载，编辑不会自动保存。</span>
  </div>
</header>
<div id="app"></div>
<footer>veval label review · 自包含离线页面 · 无任何外部资源</footer>
<script type="application/json" id="veval-data">{data_blob}</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("veval-data").textContent);
const state = {{}};   // sid -> 样本状态（与 DATA.samples 同构，可变）
DATA.samples.forEach(s => state[s.id] = s);

function labelOf(s) {{
  const lines = [];
  for (const l of s.lines) {{
    if (!l.text && !l.box) continue;              // 完全空行不导出
    const item = {{ text: l.text || "" }};
    if (Array.isArray(l.box) && l.box.length === 4 && l.box.every(Number.isFinite))
      item.box = l.box.map(Math.round);
    lines.push(item);
  }}
  const out = {{ text: lines.map(l => l.text).join("\\n"), lines }};
  if (s.fields && Object.keys(s.fields).length) out.fields = s.fields;
  out.meta = Object.assign({{}}, s.meta || {{}}, {{
    reviewed: true, reviewed_at: new Date().toISOString() }});
  return out;
}}

function download(name, obj) {{
  const blob = new Blob([JSON.stringify(obj, null, 1)], {{ type: "application/json" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}}

function cardHtml(s) {{
  const badge = s.had_label
    ? (s.meta && s.meta.draft ? '<span class="badge draft">引擎草稿</span>'
                              : '<span class="badge gt">已有标注</span>')
    : '<span class="badge none">缺标注</span>';
  let rows = "";
  s.lines.forEach((l, i) => {{
    const b = l.box || ["", "", "", ""];
    rows += `<div class="row" data-sid="${{s.id}}" data-idx="${{i}}">
      <span class="no">${{i + 1}}</span>
      <input type="text" value="${{esc(l.text)}}" placeholder="行文本" data-field="text">
      <input type="number" step="1" value="${{b[0]}}" placeholder="x1" data-field="box" data-k="0" title="x1">
      <input type="number" step="1" value="${{b[1]}}" placeholder="y1" data-field="box" data-k="1" title="y1">
      <input type="number" step="1" value="${{b[2]}}" placeholder="x2" data-field="box" data-k="2" title="x2">
      <input type="number" step="1" value="${{b[3]}}" placeholder="y2" data-field="box" data-k="3" title="y2">
      <button type="button" class="del" title="删除此行">✕</button>
    </div>`;
  }});
  if (!s.lines.length) rows = '<div class="empty">（该样本暂无标注行，点「＋添加一行」开始）</div>';
  return `<section class="card" id="card-${{s.id}}">
    <div class="card-head">
      <span class="sid">${{s.id}}</span>
      <span class="tag">${{s.filename}}</span>
      ${{badge}}
      <span style="flex:1"></span>
      <button type="button" class="primary dl-one" data-sid="${{s.id}}">下载 ${{s.label_path}}</button>
    </div>
    <div class="stage">
      <div class="imgbox">
        <img src="${{s.data}}" alt="${{s.id}}">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none"></svg>
      </div>
      <div class="editor">
        ${{rows}}
        <button type="button" class="add" data-sid="${{s.id}}">＋ 添加一行</button>
      </div>
    </div>
  </section>`;
}}

function esc(v) {{
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
}}

function drawOverlay(card, s) {{
  const img = card.querySelector("img"), svg = card.querySelector("svg");
  const W = img.naturalWidth || 100, H = img.naturalHeight || 100;
  svg.setAttribute("viewBox", `0 0 ${{W}} ${{H}}`);
  let inner = "";
  s.lines.forEach((l, i) => {{
    if (Array.isArray(l.box) && l.box.length === 4 && l.box.every(Number.isFinite)) {{
      const [x1, y1, x2, y2] = l.box;
      inner += `<rect x="${{Math.min(x1, x2)}}" y="${{Math.min(y1, y2)}}" `
        + `width="${{Math.abs(x2 - x1)}}" height="${{Math.abs(y2 - y1)}}"></rect>`;
    }}
  }});
  svg.innerHTML = inner;
}}

function render() {{
  document.getElementById("title").textContent =
    `${{DATA.title}}（${{DATA.samples.length}} 个样本 · ${{DATA.dataset}} · 生成于 ${{DATA.generated_at}}）`;
  const app = document.getElementById("app");
  app.innerHTML = DATA.samples.map(cardHtml).join("");
  DATA.samples.forEach(s => {{
    const card = document.getElementById(`card-${{s.id}}`);
    drawOverlay(card, s);
    card.querySelector("img").addEventListener("load", () => drawOverlay(card, s));
  }});
}}

// ---- 事件委托：所有编辑/导出入口 ----
document.getElementById("app").addEventListener("input", ev => {{
  const row = ev.target.closest(".row");
  if (!row) return;
  const s = state[row.dataset.sid];
  const line = s.lines[+row.dataset.idx];
  const f = ev.target.dataset.field;
  if (f === "text") {{
    line.text = ev.target.value;
  }} else if (f === "box") {{
    const k = +ev.target.dataset.k;
    const v = ev.target.value === "" ? NaN : Number(ev.target.value);
    if (!Array.isArray(line.box) || line.box.length !== 4) line.box = [null, null, null, null];
    line.box[k] = Number.isFinite(v) ? v : null;
    drawOverlay(ev.target.closest(".card"), s);
  }}
}});

document.getElementById("app").addEventListener("click", ev => {{
  const t = ev.target.closest("button");
  if (!t) return;
  const card = t.closest(".card");
  const sid = card ? card.id.slice(5) : "";
  if (t.classList.contains("add")) {{
    state[sid].lines.push({{ text: "", box: null }});
    rerenderCard(card, sid);
  }} else if (t.classList.contains("del")) {{
    const row = t.closest(".row");
    state[sid].lines.splice(+row.dataset.idx, 1);
    rerenderCard(card, sid);
  }} else if (t.classList.contains("dl-one")) {{
    download(`${{sid}}.json`, labelOf(state[t.dataset.sid]));
  }}
}});

function rerenderCard(card, sid) {{
  const tmp = document.createElement("div");
  tmp.innerHTML = cardHtml(state[sid]);
  const fresh = tmp.firstElementChild;
  card.replaceWith(fresh);
  drawOverlay(fresh, state[sid]);
  fresh.querySelector("img").addEventListener("load", () => drawOverlay(fresh, state[sid]));
}}

document.getElementById("title").insertAdjacentHTML(
  "afterend",
  '<div class="tips"><button type="button" class="primary" id="dl-all">导出全部（汇总 JSON）</button></div>'
);
document.getElementById("dl-all").addEventListener("click", () => {{
  const all = {{}};
  DATA.samples.forEach(s => {{ all[s.id] = labelOf(state[s.id]); }});
  download(`review_export_${{DATA.dataset}}.json`, {{
    dataset: DATA.dataset, exported_at: new Date().toISOString(), labels: all }});
}});

window.addEventListener("beforeunload", ev => {{
  ev.preventDefault();
  ev.returnValue = "标注编辑尚未下载，离开将丢失。";
}});

render();
</script>
</body>
</html>
"""
