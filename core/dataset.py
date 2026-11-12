"""数据集扫描与标注解析。

标注三级，可混用；缺 L1 可以由 L2 的 lines 拼接得到：
  L1  labels/<stem>.txt                -> 全文 GT
  L2  labels/<stem>.json  {"lines": [...]}  -> 行级 + 可选 box
  L3  labels/<stem>.json  {"fields": {...}} -> 字段级（P2）
"""
from __future__ import annotations

import json
from pathlib import Path

from core.config import DatasetSpec
from core.types import GroundTruth, Line, Box

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".pdf"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
EXTS_BY_MODALITY = {
    "image": IMAGE_EXTS,
    "video": VIDEO_EXTS,
    "audio": AUDIO_EXTS,
    "text": IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS,
}


def _parse_json_label(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"标注 JSON 解析失败 {path}: {e}") from e


def _lines_from_payload(payload: dict | list) -> list[Line]:
    if isinstance(payload, list):
        items = payload
    else:
        items = payload.get("lines") or payload.get("regions") or []
    out: list[Line] = []
    for it in items:
        if isinstance(it, str):
            out.append(Line(text=it))
        elif isinstance(it, dict):
            txt = it.get("text") or it.get("transcription") or it.get("value") or ""
            box = Box.from_any(it.get("box") or it.get("bbox") or it.get("points") or it.get("poly"))
            out.append(Line(text=str(txt), box=box, score=it.get("score")))
    return out


def load_ground_truth(sample_id: str, labels_dir: Path) -> GroundTruth | None:
    """找不到任何标注则返回 None（runner 完跑但不评分，只统计延迟/成本/输出量）。"""
    txt = labels_dir / f"{sample_id}.txt"
    js = labels_dir / f"{sample_id}.json"
    gt = GroundTruth(sample_id=sample_id)

    if js.is_file():
        payload = _parse_json_label(js)
        if isinstance(payload, dict) and payload.get("text"):
            gt.text = str(payload["text"])
        lines = _lines_from_payload(payload)
        if lines:
            gt.lines = lines
        if isinstance(payload, dict):
            if payload.get("fields"):
                gt.fields = payload["fields"]
            gt.meta = payload.get("meta") or {}

    if txt.is_file() and gt.text is None:
        gt.text = txt.read_text(encoding="utf-8")

    if gt.text is None and gt.lines:
        gt.text = "\n".join(l.text for l in gt.lines)

    return gt if (gt.text is not None or gt.fields is not None) else None


def list_samples(spec: DatasetSpec) -> list[tuple[str, Path]]:
    exts = EXTS_BY_MODALITY.get(spec.modality, IMAGE_EXTS)
    files = [
        p for p in sorted(spec.media_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in exts
    ]
    samples = [(p.stem, p) for p in files]
    if spec.sample_ids:
        want = set(spec.sample_ids)
        samples = [s for s in samples if s[0] in want]
    if spec.limit:
        samples = samples[: spec.limit]
    return samples


def dataset_summary(spec: DatasetSpec) -> dict:
    samples = list_samples(spec)
    with_gt = [s for s in samples if load_ground_truth(s[0], spec.labels_dir)]
    with_lines = 0
    with_box = 0
    for sid, _ in with_gt:
        gt = load_ground_truth(sid, spec.labels_dir)
        if gt and gt.lines:
            with_lines += 1
            if any(l.box for l in gt.lines):
                with_box += 1
    return {
        "name": spec.name,
        "images": len(samples),
        "with_gt": len(with_gt),
        "with_lines": with_lines,
        "with_box": with_box,
        "missing_gt": len(samples) - len(with_gt),
        "missing_gt_ids": [s for s, _ in samples if not load_ground_truth(s, spec.labels_dir)][:20],
    }
