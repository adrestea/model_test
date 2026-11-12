"""报告层数据加载：run.json → RunResult，并补齐 GT / 场景 / 媒体路径。

报告只吃 RunResult（不碰引擎、不重新推理），唯一的外部读取是：
  - results/<run>/run.json          运行结果（必需）
  - datasets/<name>/labels/*.json   逐样本 GT 文本与场景标签（可选，缺了报告降级）
  - datasets/<name>/meta.yaml       数据集级场景/来源说明（可选）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.dataset import load_ground_truth
from core.text import NormalizeConfig
from core.types import GroundTruth, Prediction, RunResult, SampleMetrics


# --------------------------------------------------------------------------
# 路径解析
# --------------------------------------------------------------------------
def resolve_run_path(arg: str | Path) -> Path:
    """接受 run.json 路径、results/<name> 目录或 run 名。"""
    path = Path(arg).expanduser()
    if path.is_file():
        return path
    candidates = [
        path / "run.json",
        Path("results") / str(arg) / "run.json",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        f"找不到运行结果: {arg}（可传 run.json 路径或 results/ 下的 run 名）"
    )


def load_run(path: str | Path) -> RunResult:
    p = resolve_run_path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    run = RunResult.from_dict(payload)
    # 记录来源，报告里标注"数据来自哪个文件"，方便复核
    run.config = dict(run.config or {})
    run.config.setdefault("_run_json", str(p))
    return run


# --------------------------------------------------------------------------
# 数据集上下文
# --------------------------------------------------------------------------
@dataclass
class DatasetContext:
    """报告需要的"运行之外"信息：GT 文本、场景标签、图片位置。"""

    name: str = ""
    lang: str = "zh"
    media_dir: Path | None = None
    labels_dir: Path | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    ground_truth: dict[str, GroundTruth] = field(default_factory=dict)
    scenes: dict[str, str] = field(default_factory=dict)
    missing_media: list[str] = field(default_factory=list)

    @property
    def scene_of(self) -> dict[str, str]:
        return self.scenes


def _dataset_root(media_dir: Path) -> Path:
    # datasets/<name>/images -> datasets/<name>
    return media_dir.parent if media_dir.name in {
        "images", "videos", "audios", "media"
    } else media_dir


def load_dataset_context(run: RunResult) -> DatasetContext:
    """从 run.config 的 dataset 段恢复数据集上下文，读不到的项一律降级不报错。"""
    ds_cfg = ((run.config or {}).get("dataset") or {})
    ctx = DatasetContext(name=str(ds_cfg.get("name") or run.run_name),
                         lang=str(ds_cfg.get("lang") or "zh"))
    media = ds_cfg.get("media_dir")
    labels = ds_cfg.get("labels_dir")
    if media:
        ctx.media_dir = Path(media)
    if labels:
        ctx.labels_dir = Path(labels)
    if ctx.media_dir and not ctx.labels_dir:
        ctx.labels_dir = _dataset_root(ctx.media_dir) / "labels"

    # meta.yaml：场景/来源/字体等说明性信息
    if ctx.media_dir:
        meta_path = _dataset_root(ctx.media_dir) / "meta.yaml"
        if meta_path.is_file():
            try:
                ctx.meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001 - meta 坏了不该阻断报告
                ctx.meta = {}

    if ctx.labels_dir and ctx.labels_dir.is_dir():
        for sample_id in dict.fromkeys(run.samples):
            gt = load_ground_truth(sample_id, ctx.labels_dir)
            if gt is not None:
                ctx.ground_truth[sample_id] = gt
                scene = str((gt.meta or {}).get("scene") or "").strip()
                if scene:
                    ctx.scenes[sample_id] = scene

    # 场景优先级：样本级 meta.scene > 数据集 meta.yaml.scene > 数据集名
    default_scene = str(ctx.meta.get("scene") or ctx.name or "未分组").strip() or "未分组"
    for sample_id in dict.fromkeys(run.samples):
        ctx.scenes.setdefault(sample_id, default_scene)
    return ctx


def media_path_for(ctx: DatasetContext, sample_id: str) -> Path | None:
    """按样本 ID 找原图；支持常见扩展名。找不到返回 None（报告显示占位）。"""
    if not ctx.media_dir:
        return None
    for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"):
        p = ctx.media_dir / f"{sample_id}{ext}"
        if p.is_file():
            return p
    # 允许 images/ 下再分子目录
    for p in ctx.media_dir.rglob(f"{sample_id}.*"):
        if p.is_file() and p.suffix.lower() in {
            ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"
        }:
            return p
    return None


def normalize_config(run: RunResult) -> NormalizeConfig:
    """复用运行时的归一化口径，保证报告 diff 与指标口径一致。"""
    return NormalizeConfig.from_dict((run.config or {}).get("normalize") or {})


def grouped_runs(run: RunResult) -> dict[str, dict[str, tuple[Prediction, SampleMetrics]]]:
    """engine_id -> sample_id -> (prediction, metrics)。"""
    if len(run.predictions) != len(run.metrics):
        raise ValueError(
            "run.json 内部不一致：predictions 与 metrics 数量不同 "
            f"({len(run.predictions)} != {len(run.metrics)})"
        )
    out: dict[str, dict[str, tuple[Prediction, SampleMetrics]]] = {}
    for pred, sm in zip(run.predictions, run.metrics):
        out.setdefault(pred.engine_id, {})[pred.sample_id] = (pred, sm)
    return out
