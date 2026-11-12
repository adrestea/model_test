"""测试公共工具：临时数据集与配置生成。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import yaml


def write_dataset(root: Path, samples: dict[str, str]) -> Path:
    """在 root/ds 下生成 images/<sid>.png + labels/<sid>.txt。"""
    ds = root / "ds"
    (ds / "images").mkdir(parents=True, exist_ok=True)
    (ds / "labels").mkdir(parents=True, exist_ok=True)
    for sid, text in samples.items():
        # 内容按 sid 区分，避免不同样本命中同一份缓存
        digest = hashlib.sha256(sid.encode()).digest()
        (ds / "images" / f"{sid}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + digest)
        (ds / "labels" / f"{sid}.txt").write_text(text, encoding="utf-8")
    return ds


def write_config(
    tmp_path: Path,
    ds: Path,
    engines: list[dict],
    tasks: Iterable[str] = ("recognize",),
    normalize: dict | None = None,
    cache: bool = False,
    **run_overrides: Any,
) -> Path:
    run: dict[str, Any] = {
        "name": "t",
        "dataset": {"name": "ds", "root": str(ds), "lang": "zh"},
        "tasks": list(tasks),
        "concurrency": 2,
        "retries": 0,
        "repeats": 1,
        "cache": cache,
        "cache_dir": str(tmp_path / "cache"),
        "timeout_s": 5,
        "out_dir": str(tmp_path / "results"),
        "normalize": normalize or {"strip_whitespace": True, "unify_punct": False},
    }
    run.update(run_overrides)
    cfg = {"run": run, "engines": engines}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path
