"""YAML 配置加载与校验。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROMPT = (
    "你是专业的 OCR 引擎。请把图片中所有可见文字完整、准确地转录为纯文本，"
    "保持原有的阅读顺序与换行，不要翻译、不要解释、不要补充任何图片中不存在的内容。"
    "数字、标点、单位、大小写必须与图中一致。只输出转录结果。"
)


@dataclass
class DatasetSpec:
    name: str
    root: Path
    media_dir: Path
    labels_dir: Path
    modality: str = "image"        # image / video / audio
    lang: str = "zh"
    limit: int | None = None
    sample_ids: list[str] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def images_dir(self) -> Path:
        """兼容别名：图片数据集下 media_dir 即 images_dir。"""
        return self.media_dir


@dataclass
class RunConfig:
    name: str
    dataset: DatasetSpec
    engines: list[dict]
    tasks: list[str]
    concurrency: int = 4
    retries: int = 1
    repeats: int = 1
    cache: bool = True
    timeout_s: float = 120.0
    normalize: dict[str, Any] = field(default_factory=dict)
    out_dir: Path = Path("results")
    raw: dict = field(default_factory=dict)
    strict: bool = False


def _dataset_spec(ds: Any) -> DatasetSpec:
    if isinstance(ds, str):
        ds = {"name": ds}
    name = ds["name"]
    modality = ds.get("modality", "image")
    root = Path(ds.get("root") or f"datasets/{name}").expanduser()
    # 目录可显式指定；否则按 modality 找默认子目录
    default_media = {
        "image": root / "images",
        "video": root / "videos",
        "audio": root / "audios",
    }.get(modality, root / "media")
    media = Path(ds.get("media_dir") or ds.get("images_dir") or default_media).expanduser()
    labels = Path(ds.get("labels_dir") or root / "labels").expanduser()
    if not media.is_dir():
        raise FileNotFoundError(
            f"数据集媒体目录不存在: {media}\n"
            f"请按 datasets/README.md 的规范放置语料。"
        )
    return DatasetSpec(
        name=name, root=root, media_dir=media, labels_dir=labels,
        modality=modality, lang=ds.get("lang", "zh"), limit=ds.get("limit"),
        sample_ids=ds.get("sample_ids"), meta=ds.get("meta") or {},
    )


def load_config(path: str | Path) -> RunConfig:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    run = raw.get("run") or {}
    engines = raw.get("engines") or []
    if not engines:
        raise ValueError(f"{path}: engines 不能为空")

    ids = [e.get("id") or e.get("type") for e in engines]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"{path}: engine id 重复 {sorted(dup)}（结果会互相覆盖）")

    return RunConfig(
        name=run.get("name") or path.stem,
        dataset=_dataset_spec(run.get("dataset") or {}),
        engines=engines,
        tasks=run.get("tasks") or ["recognize"],
        concurrency=int(run.get("concurrency", 4)),
        retries=int(run.get("retries", 1)),
        repeats=int(run.get("repeats", 1)),
        cache=bool(run.get("cache", True)),
        timeout_s=float(run.get("timeout_s", 120)),
        normalize=run.get("normalize") or {},
        out_dir=Path(run.get("out_dir") or "results"),
        raw=raw,
        strict=bool(run.get("strict", False)),
    )


def env_or_none(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None
