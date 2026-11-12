"""数据集自检：统计图片数 / 标注覆盖 / 是否有 box，缺标注的样本列 ID。

对应 CLI：`veval dataset inspect <name>`。
数据集目录规范见 datasets/README.md（images/ + labels/ + meta.yaml）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from core.dataset import IMAGE_EXTS, load_ground_truth

# 报表里最多展示多少个缺失 ID，避免刷屏
MAX_MISSING_DISPLAY = 20


def resolve_dataset_root(name: str, root: str | Path = "datasets") -> Path:
    """按名字定位数据集根目录；name 本身是路径时直接用。"""
    p = Path(name)
    if p.is_dir():
        return p
    cand = Path(root) / name
    if cand.is_dir():
        return cand
    raise FileNotFoundError(
        f"找不到数据集: {name}（找过 {p} 与 {cand}）；"
        f"可用数据集: {_list_datasets(root) or '（无）'}"
    )


def _list_datasets(root: str | Path) -> list[str]:
    base = Path(root)
    if not base.is_dir():
        return []
    return sorted(
        d.name for d in base.iterdir()
        if d.is_dir() and (d / "images").is_dir()
    )


def inspect_dataset(name: str, root: str | Path = "datasets") -> dict[str, Any]:
    """扫描数据集，返回统计字典（CLI 与测试都用它）。"""
    ds_root = resolve_dataset_root(name, root)
    images_dir = ds_root / "images"
    labels_dir = ds_root / "labels"
    if not images_dir.is_dir():
        raise FileNotFoundError(
            f"数据集缺少 images/ 目录: {ds_root}（规范见 datasets/README.md）"
        )

    images = sorted(
        p for p in images_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    samples = [(p.stem, p) for p in images]

    missing_ids: list[str] = []
    with_l2 = with_l3 = with_box = 0
    kind_counts = {"L1纯文本": 0, "L2行级": 0, "L3字段": 0}
    for sid, _ in samples:
        gt = load_ground_truth(sid, labels_dir) if labels_dir.is_dir() else None
        if gt is None:
            missing_ids.append(sid)
            continue
        if gt.lines:
            with_l2 += 1
            kind_counts["L2行级"] += 1
            if any(l.box for l in gt.lines):
                with_box += 1
        if gt.fields:
            with_l3 += 1
            kind_counts["L3字段"] += 1
        if gt.text and not gt.lines:
            kind_counts["L1纯文本"] += 1

    # 有标注文件但没对应图片（孤儿标注），帮助发现命名不一致
    orphan_labels: list[str] = []
    if labels_dir.is_dir():
        known = {sid for sid, _ in samples}
        for p in sorted(labels_dir.glob("*")):
            if p.suffix.lower() in {".json", ".txt"} and p.stem not in known:
                orphan_labels.append(p.name)

    meta: dict[str, Any] = {}
    meta_path = ds_root / "meta.yaml"
    if meta_path.is_file():
        try:
            meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 - meta 坏了不该阻断自检
            meta = {"_error": "meta.yaml 解析失败"}

    total = len(samples)
    labeled = total - len(missing_ids)
    return {
        "name": ds_root.name,
        "root": ds_root,
        "images_dir": images_dir,
        "labels_dir": labels_dir if labels_dir.is_dir() else None,
        "total": total,
        "labeled": labeled,
        "coverage": (labeled / total) if total else None,
        "with_lines": with_l2,
        "with_box": with_box,
        "with_fields": with_l3,
        "kind_counts": kind_counts,
        "missing_ids": missing_ids,
        "orphan_labels": orphan_labels,
        "meta": meta,
        "extensions": sorted({p.suffix.lower() for _, p in samples}),
        "has_meta_yaml": meta_path.is_file(),
    }


def format_inspect(info: dict[str, Any]) -> str:
    """把统计结果渲染成人类可读文本（CLI 用）。"""
    lines = [
        f"数据集 {info['name']}（{info['root']}）",
        f"  图片数        {info['total']}（扩展名 {', '.join(info['extensions']) or '-'}）",
        f"  有标注        {info['labeled']}/{info['total']}"
        + (
            f"（覆盖率 {info['coverage'] * 100:.0f}%）"
            if info["coverage"] is not None else ""
        ),
        f"  L2 行级标注   {info['with_lines']}",
        f"  含像素 box    {info['with_box']}",
        f"  L3 字段标注   {info['with_fields']}",
        f"  meta.yaml     {'有' if info['has_meta_yaml'] else '无'}",
    ]
    meta = info["meta"]
    if meta:
        for key in ("lang", "scene", "source"):
            if meta.get(key):
                lines.append(f"  meta.{key:<9} {meta[key]}")
    missing = info["missing_ids"]
    if missing:
        shown = ", ".join(missing[:MAX_MISSING_DISPLAY])
        more = f" …… 另有 {len(missing) - MAX_MISSING_DISPLAY} 个" \
            if len(missing) > MAX_MISSING_DISPLAY else ""
        lines.append(f"  ⚠ 缺标注 {len(missing)} 个：{shown}{more}")
        lines.append(
            "    提示：veval label draft 可生成草稿 GT，veval label review 可人工校正"
        )
    if info["orphan_labels"]:
        lines.append(f"  ⚠ 有标注无图片 {len(info['orphan_labels'])} 个："
                     + ", ".join(info["orphan_labels"][:MAX_MISSING_DISPLAY]))
    return "\n".join(lines)
