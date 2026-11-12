"""veval 命令行入口：run / baseline / report / dataset / label / synth。

用法示例：
  .venv/bin/python cli.py run -c configs/demo.yaml
  .venv/bin/python cli.py baseline freeze results/demo/run.json
  .venv/bin/python cli.py baseline diff results/demo/run.json results/baselines/demo.json
  .venv/bin/python cli.py report results/demo -o results/demo/report
  .venv/bin/python cli.py dataset inspect smoke
  .venv/bin/python cli.py synth --name synth_smoke -n 8 --rotate 4 --noise 6
  .venv/bin/python cli.py label draft smoke --engine ocr.rapidocr
  .venv/bin/python cli.py label review smoke -o smoke_review.html
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import unicodedata
from pathlib import Path
from typing import Iterable, Sequence

# 可编辑安装的 finder 只映射了 core/metrics/runner/adapters/cli；
# tools 与 report 是后加的目录包，不在映射里。把项目根补进 sys.path，
# 保证 `veval` 控制台脚本在任何工作目录下都能 import 到这两个包。
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.config import load_config
from runner.aggregate import summarize_run
from runner.baseline import diff_report, freeze, resolve_baseline
from runner.run import Runner, load_run, resolve_run_path, save_run
from tools import synth as tools_synth

KEY_DIFF_METRICS = (
    "cer", "sub_rate", "del_rate", "ins_rate", "char_recall",
    "line_f1", "box_iou_mean", "error_rate", "latency_p50", "cost_per_1000",
)


# ---------- 表格渲染（按显示宽度对齐，兼容中文） ----------
def _disp_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    gap = max(0, width - _disp_width(text))
    return (" " * gap + text) if right else (text + " " * gap)


def format_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    right_align_from: int = 1,
) -> str:
    """简易等宽表格。中文按 2 列宽计算，数字列右对齐。"""
    data = [list(map(str, row)) for row in rows]
    widths = [
        max([_disp_width(str(h))] + [_disp_width(r[i]) for r in data])
        for i, h in enumerate(headers)
    ]
    align_right = [i >= right_align_from for i in range(len(headers))]
    out = [
        "  ".join(_pad(str(h), widths[i], align_right[i]) for i, h in enumerate(headers)),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row in data:
        out.append(
            "  ".join(_pad(row[i], widths[i], align_right[i]) for i in range(len(headers)))
        )
    return "\n".join(out)


def _ratio(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _usd(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def summary_table(summary: dict[str, dict]) -> str:
    headers = [
        "引擎", "样本", "成功", "错误率", "CER", "SUB", "DEL", "INS",
        "完整率", "行F1", "定位IoU", "P50(ms)", "P90(ms)", "成本/千",
    ]
    rows: list[list[str]] = []
    for engine_id in sorted(summary):
        item = summary[engine_id]
        m = item.get("metrics") or {}
        lat = item.get("latency_ms") or {}
        cost = item.get("cost") or {}
        error_rate = item.get("error_rate")
        rows.append([
            engine_id,
            str(item.get("samples_total", 0)),
            str(item.get("samples_ok", 0)),
            "-" if error_rate is None else f"{error_rate * 100:.1f}%",
            _ratio(m.get("cer")),
            _ratio(m.get("sub_rate")),
            _ratio(m.get("del_rate")),
            _ratio(m.get("ins_rate")),
            _ratio(m.get("char_recall")),
            _ratio(m.get("line_f1")),
            _ratio(m.get("box_iou_mean")),
            _ms(lat.get("p50")),
            _ms(lat.get("p90")),
            _usd(cost.get("per_1000")),
        ])
    return format_table(headers, rows)


# ---------- 子命令 ----------
def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.limit is not None:
        if args.limit < 0:
            raise ValueError("--limit 不能为负数")
        cfg = dataclasses.replace(
            cfg, dataset=dataclasses.replace(cfg.dataset, limit=args.limit)
        )
    if args.concurrency is not None:
        if args.concurrency < 1:
            raise ValueError("--concurrency 至少为 1")
        cfg = dataclasses.replace(cfg, concurrency=args.concurrency)
    if args.no_cache:
        cfg = dataclasses.replace(cfg, cache=False)
    if args.run_name:
        cfg = dataclasses.replace(cfg, name=args.run_name)
    if args.engines:
        wanted = {x.strip() for x in args.engines.split(",") if x.strip()}
        known = {e.get("id") or e.get("type") for e in cfg.engines}
        unknown = wanted - known
        if unknown:
            raise ValueError(f"配置里没有这些引擎: {sorted(unknown)}；可选: {sorted(known)}")
        cfg = dataclasses.replace(
            cfg,
            engines=[e for e in cfg.engines if (e.get("id") or e.get("type")) in wanted],
        )

    progress = None
    if not args.quiet:
        def progress(msg: str) -> None:
            print(msg, file=sys.stderr, flush=True)

    runner = Runner(cfg, progress=progress)
    run = runner.run()
    out_dir = Path(args.out) if args.out else cfg.out_dir
    run_path = save_run(run, out_dir, cfg.name)
    summary = summarize_run(run)

    print(
        f"\n运行完成：{run.run_name}｜样本 {len(run.samples)} 个｜"
        f"预测 {len(run.predictions)} 条｜耗时 {run.env.get('duration_s')}s"
    )
    print(summary_table(summary))
    errors = run.env.get("engine_build_errors") or []
    if errors:
        print("\n引擎构建失败（已跳过）:")
        for item in errors:
            print(f"  - {item.get('engine')}: {item.get('error')}")
    skipped = (run.env.get("skipped") or {})
    if skipped.get("count"):
        print(f"\n跳过不支持的组合 {skipped['count']} 个：")
        for reason, count in (skipped.get("reasons") or {}).items():
            print(f"  - {reason}（{count} 个）")
    print(f"\n结果已落盘：{run_path}")
    return 0


def cmd_baseline_freeze(args: argparse.Namespace) -> int:
    run_path = resolve_run_path(args.run)
    run = load_run(run_path)
    out = Path(args.out) if args.out else None
    if out is not None and out.is_dir():
        out = out / f"{run.run_name}.json"
    baseline_path = freeze(run, out, source=str(run_path))
    print(f"基线已冻结：{baseline_path}（来源 {run_path}，run={run.run_name}）")
    return 0


def _verdict_mark(verdict: str) -> str:
    return {"变好": "↑ 变好", "变坏": "↓ 变坏"}.get(verdict, verdict)


def cmd_baseline_diff(args: argparse.Namespace) -> int:
    run_path = resolve_run_path(args.run)
    baseline_path = resolve_baseline(args.baseline)
    run = load_run(run_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    report = diff_report(run, baseline)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    metrics = report["metric_rows"]
    if not args.all:
        metrics = [r for r in metrics if r["metric"] in KEY_DIFF_METRICS]
    rows = [
        [
            r["engine_id"],
            r["label"],
            _ratio(r["baseline"], 4),
            _ratio(r["current"], 4),
            "-" if r["delta"] is None else f"{r['delta']:+.4f}",
            _verdict_mark(r["verdict"]),
        ]
        for r in metrics
    ]
    print(
        f"基线对比：当前 run={run.run_name}（{run_path}）"
        f"｜基线 run={report.get('baseline_run_name')}（{baseline_path}）"
    )
    print("口径：指标为成功样本均值；CER/SUB/DEL/INS/错误率/延迟/成本 越小越好，完整率/行F1/定位IoU 越大越好。\n")
    if report.get("sample_set_changed"):
        details = "，".join(
            f"{engine} 基线 {item['baseline']} 条/当前 {item['current']} 条"
            for engine, item in (report.get("sample_sets") or {}).items()
            if item["baseline"] != item["current"]
        )
        print(f"⚠ 样本集不一致（{details}）：均值涨跌含样本构成变化，请结合样本级变化判断。\n")
    print(format_table(["引擎", "指标", "基线", "当前", "变化", "结论"], rows, right_align_from=2))

    changes = report["sample_changes"]
    counts = changes["counts"]
    print(f"\n样本级变化（按 CER）：变好 {counts.get('变好', 0)}｜"
          f"变坏 {counts.get('变坏', 0)}｜持平 {counts.get('持平', 0)}｜"
          f"缺失 {counts.get('缺失', 0)}"
    )
    limit = max(0, args.top)
    for verdict in ("变好", "变坏"):
        picked = [s for s in changes["rows"] if s["verdict"] == verdict]
        picked.sort(key=lambda s: abs(s["delta"] or 0.0), reverse=True)
        for s in picked[:limit]:
            print(
                f"  [{verdict}] {s['engine_id']} · {s['sample_id']}："
                f"CER {_ratio(s['before'], 4)} → {_ratio(s['after'], 4)}"
            )
        if len(picked) > limit:
            print(f"  …… 另有 {len(picked) - limit} 个{verdict}样本未展示")
    return 0


# ---------- report / dataset / synth / label ----------
def cmd_report(args: argparse.Namespace) -> int:
    from report.render import ReportOptions, parse_formats, render_all
    from report.stats import DEFAULT_ACCURACY_METRIC

    opts = ReportOptions(
        title=args.title or "",
        rate=args.rate,
        accuracy_metric=args.accuracy or DEFAULT_ACCURACY_METRIC,
        sort=args.sort,
        max_samples=args.max_samples,
        thumb_px=args.thumb_px,
        include_images=not args.no_images,
        formats=parse_formats(args.formats),
    )
    written = render_all(args.run, args.out, opts)
    print(f"报告已生成（run={args.run} → {args.out}）：")
    for fmt, path in written.items():
        print(f"  - {path}")
    return 0


def cmd_dataset_inspect(args: argparse.Namespace) -> int:
    from tools.inspect import format_inspect, inspect_dataset

    info = inspect_dataset(args.name, args.root)
    print(format_inspect(info))
    return 0


def cmd_synth(args: argparse.Namespace) -> int:
    from tools.synth import SynthOptions, generate_dataset

    opts = SynthOptions(
        name=args.name,
        out_root=args.out_root,
        count=args.count,
        prefix=args.prefix,
        font=args.font,
        font_size=args.font_size,
        lines=args.lines,
        min_lines=args.min_lines,
        max_lines=args.max_lines,
        width=args.width,
        height=args.height,
        noise=args.noise,
        blur=args.blur,
        rotate=args.rotate,
        jpeg_quality=args.jpeg_quality,
        scale=args.scale,
        seed=args.seed,
    )
    result = generate_dataset(opts)
    sample = result["label_sample"]
    first_box = sample["lines"][0]["box"]
    first_line = sample["text"].splitlines()[0]
    print(
        f"合成完成：{result['count']} 张 → {result['images_dir']}"
        f"（标注 {result['labels_dir']}，meta {result['meta_path']}）"
    )
    print(
        f"标注抽样 {result['sample_ids'][0]}：{len(sample['lines'])} 行 | "
        f"text=\"{first_line}…\" | box[0]={first_box}"
    )
    print(f"下一步：veval run -c <配置> 或 veval dataset inspect {result['name']}")
    return 0


def cmd_label_draft(args: argparse.Namespace) -> int:
    from tools.label import draft_labels, resolve_engine_spec

    spec = resolve_engine_spec(
        config=args.config, engine_id=args.engine_id,
        engine=args.engine, params=args.params,
    )
    result = draft_labels(
        args.dataset, spec, root=args.root,
        overwrite=args.overwrite, limit=args.limit,
    )
    print(
        f"草稿完成：引擎 {result['engine_id']}（{result['engine_type']}） → "
        f"{result['labels_dir']}"
    )
    print(
        f"样本 {result['samples']} 个：写入 {len(result['written'])}｜"
        f"跳过已有 {len(result['skipped'])}｜失败 {len(result['failed'])}"
    )
    if result["skipped"]:
        print(f"  跳过（已有标注）: {', '.join(result['skipped'])}")
    if result["failed"]:
        print("失败样本:")
        for item in result["failed"]:
            print(f"  - {item['sample_id']}: {item['error']}")
    print(f"下一步：veval label review {result['dataset']} 人工校正后即为标准 GT")
    return 0


def cmd_label_review(args: argparse.Namespace) -> int:
    from tools.label import build_review_page

    path = build_review_page(args.dataset, root=args.root, out=args.out)
    print(f"校正页已生成：{path}")
    print("浏览器打开（断网可用，无外链）；编辑后点「下载 labels/<id>.json」拷回数据集 labels/ 目录。")
    return 0


# ---------- 参数解析 ----------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veval", description="OCR / VLM 图文识别评测与选型系统"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="按配置跑引擎 × 数据集矩阵并落盘")
    p_run.add_argument("-c", "--config", required=True, help="YAML 配置路径")
    p_run.add_argument("--limit", type=int, default=None, help="只跑前 N 个样本（冒烟用）")
    p_run.add_argument("--run-name", default=None, help="覆盖 run 名（决定 results/<run>/ 目录）")
    p_run.add_argument("--out", default=None, help="结果根目录，默认取配置 out_dir")
    p_run.add_argument("--engines", default=None, help="只跑指定引擎，逗号分隔")
    p_run.add_argument("--concurrency", type=int, default=None, help="并发数覆盖")
    p_run.add_argument("--no-cache", action="store_true", help="关闭预测缓存")
    p_run.add_argument("-q", "--quiet", action="store_true", help="不打印进度")
    p_run.set_defaults(func=cmd_run)

    p_base = sub.add_parser("baseline", help="基线冻结与对比")
    base_sub = p_base.add_subparsers(dest="baseline_cmd", required=True)

    p_freeze = base_sub.add_parser("freeze", help="把一次 run 冻结为基线")
    p_freeze.add_argument("run", help="run.json 路径或 results/ 下的 run 名")
    p_freeze.add_argument("-o", "--out", default=None, help="基线文件路径（默认 results/baselines/<run>.json）")
    p_freeze.set_defaults(func=cmd_baseline_freeze)

    p_diff = base_sub.add_parser("diff", help="对比当前 run 与基线")
    p_diff.add_argument("run", help="当前 run.json 路径或 run 名")
    p_diff.add_argument("baseline", help="基线文件路径或基线名")
    p_diff.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_diff.add_argument("--all", action="store_true", help="展示全部指标（默认只看关键指标）")
    p_diff.add_argument("--top", type=int, default=5, help="每类样本变化最多展示几条，默认 5")
    p_diff.set_defaults(func=cmd_baseline_diff)

    # ---- report：渲染报告 ----
    p_report = sub.add_parser("report", help="把 run 渲染为 HTML / Markdown / CSV 报告")
    p_report.add_argument("run", help="run.json 路径或 results/ 下的 run 名")
    p_report.add_argument("-o", "--out", default="results/report", help="报告输出目录")
    p_report.add_argument("--formats", default="html,md,csv", help="格式逗号分隔：html,md,csv")
    p_report.add_argument("--title", default=None, help="报告标题（默认用 run 名）")
    p_report.add_argument("--rate", type=float, default=7.2, help="USD→CNY 汇率，默认 7.2")
    p_report.add_argument("--sort", default="cer", help="总榜排序键（cer/char_recall/line_f1/...）")
    p_report.add_argument("--accuracy", default=None, help="成本表的准确率口径（默认同 --sort）")
    p_report.add_argument("--max-samples", type=int, default=None, help="逐样本对照最多显示几个")
    p_report.add_argument("--thumb-px", type=int, default=420, help="缩略图最长边像素")
    p_report.add_argument("--no-images", action="store_true", help="不内嵌图片，报告更小")
    p_report.set_defaults(func=cmd_report)

    # ---- dataset：数据集自检 ----
    p_ds = sub.add_parser("dataset", help="数据集检查")
    ds_sub = p_ds.add_subparsers(dest="dataset_cmd", required=True)
    p_ins = ds_sub.add_parser(
        "inspect", help="统计图片数/标注覆盖/box覆盖，缺标注的样本列 ID")
    p_ins.add_argument("name", help="数据集名（datasets/ 下）或路径")
    p_ins.add_argument("--root", default="datasets", help="数据集根目录，默认 datasets/")
    p_ins.set_defaults(func=cmd_dataset_inspect)

    # ---- synth：合成数据集 ----
    p_synth = sub.add_parser(
        "synth", help="PIL 渲染合成中文数据集（自动产带真实像素 box 的 L2 标注）")
    p_synth.add_argument("--name", required=True, help="数据集名 → datasets/<name>/")
    p_synth.add_argument("--out-root", default="datasets", help="数据集根目录")
    p_synth.add_argument("-n", "--count", type=int, default=8, help="生成图片数，默认 8")
    p_synth.add_argument("--prefix", default="synth", help="样本 ID 前缀，默认 synth")
    p_synth.add_argument("--font", default=tools_synth.DEFAULT_FONT, help="中文字体路径")
    p_synth.add_argument("--font-size", type=int, default=32, help="字号，默认 32")
    p_synth.add_argument("--lines", type=int, default=None, help="固定每图行数")
    p_synth.add_argument("--min-lines", type=int, default=2, help="每图最少行数，默认 2")
    p_synth.add_argument("--max-lines", type=int, default=5, help="每图最多行数，默认 5")
    p_synth.add_argument("--width", type=int, default=None, help="画布宽（默认按文本自适应）")
    p_synth.add_argument("--height", type=int, default=None, help="画布高")
    p_synth.add_argument("--noise", type=float, default=0.0, help="高斯噪点 sigma，默认关")
    p_synth.add_argument("--blur", type=float, default=0.0, help="高斯模糊半径，默认关")
    p_synth.add_argument("--rotate", type=float, default=0.0, help="随机旋转幅度±度，默认关")
    p_synth.add_argument("--jpeg-quality", type=int, default=None,
                         help="JPEG 质量 1-95；不给则存 PNG")
    p_synth.add_argument("--scale", type=float, default=1.0, help="整体缩放系数，默认 1.0")
    p_synth.add_argument("--seed", type=int, default=42, help="随机种子，默认 42")
    p_synth.set_defaults(func=cmd_synth)

    # ---- label：标注草稿与人工校正 ----
    p_label = sub.add_parser("label", help="标注草稿（draft）与人工校正页（review）")
    label_sub = p_label.add_subparsers(dest="label_cmd", required=True)
    p_draft = label_sub.add_parser("draft", help="用指定引擎给数据集生成草稿 GT")
    p_draft.add_argument("dataset", help="数据集名（datasets/ 下）或路径")
    p_draft.add_argument("-c", "--config", default=None,
                          help="评测配置路径（配合 --engine-id 选引擎）")
    p_draft.add_argument("--engine-id", default=None,
                         help="从配置里挑的引擎 id（配合 -c）")
    p_draft.add_argument("--engine", default=None,
                          help="引擎类型名，或完整 JSON spec，如 '{\"type\": \"ocr.rapidocr\"}'")
    p_draft.add_argument("--params", default=None, help="引擎 params 的 JSON 字符串")
    p_draft.add_argument("--overwrite", action="store_true",
                         help="覆盖已存在的标注（默认跳过已有标注）")
    p_draft.add_argument("--limit", type=int, default=None, help="只处理前 N 个样本")
    p_draft.add_argument("--root", default="datasets", help="数据集根目录")
    p_draft.set_defaults(func=cmd_label_draft)
    p_review = label_sub.add_parser("review", help="生成本地 HTML 标注校正页（无外链）")
    p_review.add_argument("dataset", help="数据集名（datasets/ 下）或路径")
    p_review.add_argument("--root", default="datasets", help="数据集根目录")
    p_review.add_argument("-o", "--out", default=None,
                          help="HTML 输出路径，默认 results/label_review/<数据集>.html")
    p_review.set_defaults(func=cmd_label_review)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
