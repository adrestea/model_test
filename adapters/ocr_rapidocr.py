"""RapidOCR（PaddleOCR 模型 + onnxruntime，纯 CPU 可跑）适配。

type: ocr.rapidocr
configs/full.yaml:
    - id: rapidocr
      type: ocr.rapidocr
      params: { device: cpu }
      cost: { per_image: 0 }

参数（params）：
    device        仅作声明（onnxruntime CPU / 或 CUDAExecutionProvider 版本）
    det_model_path / rec_model_path / cls_model_path  自定义模型路径（可选）
    use_angle_cls 是否做方向分类，默认 true（等价 rapidocr 的 use_angle_cls）
    rec_batch_num 识别 batch，默认 6
    box_score_thresh 行置信度阈值，低于该值的行丢弃，默认 0.0（不丢）
"""
from __future__ import annotations

import time
from typing import Any

from adapters._ocr_common import (
    image_file,
    image_size,
    lines_to_text,
    poly_to_box,
    require_module,
)
from adapters.base import BaseEngine, register
from core.types import Box, EngineOutput, EngineRequest, Line

INSTALL_CMD = (
    "uv pip install --python .venv/bin/python rapidocr-onnxruntime\n"
    "    # 或：uv pip install --python .venv/bin/python rapidocr onnxruntime"
)


@register("ocr.rapidocr")
class RapidOCREngine(BaseEngine):
    type_name = "ocr.rapidocr"
    capabilities = ("recognize", "lines", "boxes")
    modalities = ("image",)

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self._engine = None          # 懒加载，warmup() 或首次 predict 时创建
        self._load_ms: float | None = None

    # ---- 生命周期 ----
    def _load(self):
        if self._engine is not None:
            return self._engine
        t0 = time.perf_counter()
        mod = require_module(
            "rapidocr_onnxruntime",
            INSTALL_CMD,
            why="RapidOCR 是本地 CPU OCR 引擎，需要 rapidocr-onnxruntime 包（含内置 ONNX 模型，无需 torch）。",
        )
        kwargs: dict[str, Any] = {}
        legacy = hasattr(mod, "RapidOCR") and "onnxruntime" in getattr(mod, "__name__", "")
        use_cls = self.params.get("use_angle_cls")
        if use_cls is not None:
            # 1.x(onnxruntime) 用 use_cls，2.x(rapidocr) 用 use_angle_cls
            kwargs["use_cls" if legacy else "use_angle_cls"] = bool(use_cls)
        if self.params.get("text_score") is not None:
            kwargs["text_score"] = float(self.params["text_score"])
        for key in ("det_model_path", "rec_model_path", "cls_model_path"):
            if self.params.get(key):
                kwargs[key] = self.params[key]
        if self.params.get("rec_batch_num"):
            kwargs["rec_batch_num"] = int(self.params["rec_batch_num"])
        if str(self.device).startswith(("cuda", "gpu")):
            for prefix in ("det", "cls", "rec"):
                kwargs[f"{prefix}_use_cuda"] = True

        self._engine = mod.RapidOCR(**kwargs)
        self._load_ms = (time.perf_counter() - t0) * 1000
        return self._engine

    def warmup(self) -> None:
        self._load()

    # ---- 推理 ----
    def _predict(self, req: EngineRequest) -> EngineOutput:
        import numpy as np  # rapidocr 的硬依赖，随包安装

        engine = self._load()
        thresh = float(self.params.get("box_score_thresh", 0.0) or 0.0)

        with image_file(req) as path:
            size = image_size(path)
            t0 = time.perf_counter()
            out = engine(path)
            infer_ms = (time.perf_counter() - t0) * 1000

        # rapidocr 两个大版本的返回形状：
        #   旧版: (result, elapse)  result = [[box, text, score], ...]
        #   新版: (result, elapse) 或 TextRecOutput 对象，result 结构相同
        result, elapse = _split_result(out)

        lines: list[Line] = []
        dropped = 0
        for item in result or []:
            parsed = _parse_item(item)
            if parsed is None:
                continue
            box, text, score = parsed
            if not text:
                continue
            if thresh and score is not None and score < thresh:
                dropped += 1
                continue
            lines.append(Line(text=text, box=box, score=score))

        lines.sort(key=_reading_order)

        meta: dict[str, Any] = {
            "engine": "rapidocr",
            "image_size": list(size) if size else None,
            "infer_ms": round(infer_ms, 2),
            "load_ms": round(self._load_ms, 2) if self._load_ms is not None else None,
        }
        if elapse:
            meta["stage_ms"] = _elapse_dict(elapse)
        if dropped:
            meta["dropped_low_score"] = dropped

        return EngineOutput(
            text=lines_to_text(lines),
            lines=lines,
            usage={"images": 1},
            raw=result,
            meta=meta,
        )


# --------------------------------------------------------------------------
# 解析辅助
# --------------------------------------------------------------------------
def _split_result(out: Any) -> tuple[Any, Any]:
    """(result, elapse) 解包；容错单返回值 / None。"""
    if out is None:
        return None, None
    if isinstance(out, tuple) and len(out) == 2:
        return out[0], out[1]
    if isinstance(out, list) and len(out) == 2 and isinstance(out[1], list) and out[1] and isinstance(out[1][0], (int, float)):
        return out[0], out[1]
    return out, None


def _parse_item(item: Any) -> tuple[Box | None, str, float | None] | None:
    """单行结果 → (box, text, score)。兼容 [box, text, score] / dict / 4 元组。"""
    if isinstance(item, dict):
        text = str(item.get("text") or item.get("txt") or "")
        box = poly_to_box(item.get("box") or item.get("points") or item.get("dt_box"))
        score = item.get("score") or item.get("confidence")
        return box, text, float(score) if score is not None else None

    if isinstance(item, (list, tuple)):
        if len(item) >= 3 and isinstance(item[1], str):
            box = poly_to_box(item[0])
            try:
                score = float(item[2])
            except (TypeError, ValueError):
                score = None
            return box, item[1], score
        # 新版本可能给出 [box, (text, score)]
        if len(item) == 2 and isinstance(item[0], (list, tuple, dict)) and isinstance(item[1], (list, tuple)) \
                and len(item[1]) >= 1 and isinstance(item[1][0], str):
            txt, score = item[1][0], item[1][1] if len(item[1]) > 1 else None
            return poly_to_box(item[0]), txt, float(score) if score is not None else None
    return None


def _elapse_dict(elapse: Any) -> dict[str, float] | None:
    try:
        return {
            "det_ms": round(float(elapse[0]) * 1000, 2),
            "cls_ms": round(float(elapse[1]) * 1000, 2),
            "rec_ms": round(float(elapse[2]) * 1000, 2),
        }
    except Exception:  # noqa: BLE001
        return None


def _reading_order(line: Line) -> tuple[float, float]:
    """阅读顺序：先按行中心 y，再按 x。无 box 的排最后。"""
    if line.box is None:
        return (float("inf"), float("inf"))
    return ((line.box.y1 + line.box.y2) / 2, line.box.x1)
