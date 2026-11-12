"""报告编排：RunResult → 报告数据包（bundle）→ 各格式渲染。

分三层，互不耦合：
  loader.py  读 run.json + 数据集上下文
  stats.py   算统计（总榜/分场景/逐样本/延迟/成本）
  html.py / markdown.py / csv_out.py  只负责"把 bundle 变成文本"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from core.types import RunResult

from report.loader import DatasetContext, load_dataset_context, load_run, normalize_config
from report.stats import (
    DEFAULT_ACCURACY_METRIC,
    SORT_KEYS,
    EngineStat,
    SampleRow,
    build_engine_stats,
    build_sample_rows,
    build_scene_stats,
    cost_rows,
    latency_rows,
    selection_summary,
    sort_engine_stats,
)


@dataclass
class ReportOptions:
    """报告渲染选项（CLI 参数一一对应）。"""

    title: str = ""
    rate: float = 7.2                                  # USD→CNY 汇率，可配
    accuracy_metric: str = DEFAULT_ACCURACY_METRIC     # 成本表的"准确率"
    sort: str = "cer"                                  # 总榜排序键
    max_samples: int | None = None                     # 逐样本对照最多显示几个
    thumb_px: int = 420                                # 缩略图最长边
    include_images: bool = True                        # 关掉可让 HTML 变小
    formats: tuple[str, ...] = ("html", "md", "csv")

    def validate(self) -> "ReportOptions":
        if self.sort not in SORT_KEYS:
            raise ValueError(f"不支持的排序键: {self.sort}，可选 {sorted(SORT_KEYS)}")
        if self.accuracy_metric not in SORT_KEYS:
            raise ValueError(
                f"不支持的准确率口径: {self.accuracy_metric}，可选 {sorted(SORT_KEYS)}"
            )
        if self.rate <= 0:
            raise ValueError("汇率必须为正数")
        return self


@dataclass
class ReportBundle:
    """渲染所需的一切（纯数据，三种格式共用，保证口径一致）。"""

    run: RunResult
    ctx: DatasetContext
    opts: ReportOptions
    engines: list[EngineStat]
    scenes: dict[str, list[EngineStat]]
    samples: list[SampleRow]
    summary: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""
    run_json: str = ""

    # ---- 便捷访问 ----
    @property
    def engine_ids(self) -> list[str]:
        return [s.engine_id for s in self.engines]

    @property
    def title(self) -> str:
        return self.opts.title or f"{self.run.run_name} 识别引擎评测报告"

    @property
    def accuracy_label(self) -> str:
        return SORT_KEYS[self.opts.accuracy_metric][0]

    def cost_table(self) -> list[dict[str, Any]]:
        return cost_rows(self.engines, self.opts.rate, self.opts.accuracy_metric)

    def latency_table(self) -> list[dict[str, Any]]:
        return latency_rows(self.engines)

    def sample_stats(self) -> dict[str, int]:
        total = len(list(dict.fromkeys(self.run.samples)))
        with_gt = len(self.ctx.ground_truth)
        errored = sum(1 for p in self.run.predictions if p.error is not None)
        return {
            "samples": total,
            "with_gt": with_gt,
            "engines": len(self.engines),
            "predictions": len(self.run.predictions),
            "errors": errored,
        }

    @property
    def normalize(self):
        return normalize_config(self.run)


def build_bundle(run: RunResult, opts: ReportOptions,
                 ctx: DatasetContext | None = None) -> ReportBundle:
    """把一次运行变成可渲染的数据包。"""
    opts.validate()
    ctx = ctx or load_dataset_context(run)
    engines = sort_engine_stats(
        build_engine_stats(run, ctx, rate=opts.rate, accuracy_metric=opts.accuracy_metric),
        opts.sort,
    )
    scenes = build_scene_stats(run, ctx, rate=opts.rate, accuracy_metric=opts.accuracy_metric)
    samples = build_sample_rows(
        run, ctx, engine_order=[s.engine_id for s in engines], limit=opts.max_samples
    )
    summary = selection_summary(engines, opts.rate, opts.accuracy_metric)
    return ReportBundle(
        run=run,
        ctx=ctx,
        opts=opts,
        engines=engines,
        scenes=scenes,
        samples=samples,
        summary=summary,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        run_json=str((run.config or {}).get("_run_json") or ""),
    )


def render_all(
    run: str | Path | RunResult,
    out_dir: str | Path = "results/report",
    opts: ReportOptions | None = None,
) -> dict[str, Path]:
    """渲染全部请求的格式，返回 {格式: 文件路径}。

    文件名带 run 名，便于同一目录下放多份报告：
      report.html / report.md / engines.csv / samples.csv / scenes.csv / costs.csv
    """
    opts = (opts or ReportOptions()).validate()
    run_obj = run if isinstance(run, RunResult) else load_run(run)
    bundle = build_bundle(run_obj, opts)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    if "html" in opts.formats:
        from report.html import render_html

        path = target / "report.html"
        path.write_text(render_html(bundle), encoding="utf-8")
        written["html"] = path
    if "md" in opts.formats:
        from report.markdown import render_markdown

        path = target / "report.md"
        path.write_text(render_markdown(bundle), encoding="utf-8")
        written["md"] = path
    if "csv" in opts.formats:
        from report.csv_out import write_csvs

        for path in write_csvs(bundle, target):
            written[path.name] = path
    return written


def parse_formats(value: str | Iterable[str]) -> tuple[str, ...]:
    """'html,md,csv' → ('html','md','csv')，去重保序并校验。"""
    if isinstance(value, str):
        raw = [v.strip().lower() for v in value.replace("，", ",").split(",")]
    else:
        raw = [str(v).strip().lower() for v in value]
    allowed = {"html", "md", "csv"}
    out: list[str] = []
    for v in raw:
        if not v:
            continue
        if v not in allowed:
            raise ValueError(f"不支持的格式: {v}，可选 {sorted(allowed)}")
        if v not in out:
            out.append(v)
    return tuple(out or ["html"])
