"""PaddleOCR（PP-OCR 本地推理）适配，兼容 2.x / 3.x 两代 API。

type: ocr.paddleocr
configs/full.yaml:
    - id: paddleocr
      type: ocr.paddleocr
      params: { lang: ch, device: cpu, use_angle_cls: true }
      cost: { per_image: 0 }

参数（params）：
    lang           语言模型，默认 ch（中文）
    device         cpu / cuda:0（2.x 自动映射成 use_gpu）
    use_angle_cls  方向分类，默认 true
    det / rec / cls  是否启用对应子模型，默认都 true（可选）
    box_score_thresh 行置信度阈值，默认 0.0
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
    "uv pip install --python .venv/bin/python paddlepaddle paddleocr\n"
    "    # 注意：paddlepaddle 轮子较大（数百 MB），无 GPU 时装 CPU 版：\n"
    "    # uv pip install --python .venv/bin/python paddlepaddle==2.6.2 paddleocr==2.9.1\n"
    "    # 首次识别会自动下载 PP-OCR 模型到 ~/.paddleocr/"
)


@register("ocr.paddleocr")
class PaddleOCREngine(BaseEngine):
    type_name = "ocr.paddleocr"
    capabilities = ("recognize", "lines", "boxes")
    modalities = ("image",)

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self._engine = None
        self._major = 0
        self._load_ms: float | None = None

    def _validate(self) -> None:
        self.lang = str(self.params.get("lang") or "ch")
        self.use_angle_cls = bool(self.params.get("use_angle_cls", True))

    # ---- 生命周期 ----
    def _load(self):
        if self._engine is not None:
            return self._engine

        mod = require_module(
            "paddleocr",
            INSTALL_CMD,
            why="PaddleOCR 依赖 paddlepaddle 深度学习框架，本 adapter 不引入 torch。",
        )
        t0 = time.perf_counter()
        cls = getattr(mod, "PaddleOCR", None)
        if cls is None:  # 极老版本包名不同
            raise RuntimeError(
                "paddleocr 包结构异常：找不到 PaddleOCR 类。\n请重装：\n    " + INSTALL_CMD
            )

        self._major = _major_version(getattr(mod, "__version__", ""))
        device = str(self.params.get("device") or "cpu")

        if self._major >= 3:
            kwargs: dict[str, Any] = {"lang": self.lang}
            if "use_angle_cls" in self.params:
                # 3.x 改名，旧参数会被拒绝
                kwargs["use_textline_orientation"] = self.use_angle_cls
            if device and device != "auto":
                kwargs["device"] = device
            self._engine = cls(**kwargs)
        else:
            kwargs = {
                "lang": self.lang,
                "use_angle_cls": self.use_angle_cls,
                "show_log": bool(self.params.get("show_log", False)),
                "use_gpu": device.startswith("cuda") or device.startswith("gpu"),
            }
            for key in ("det", "rec", "cls"):
                if key in self.params:
                    kwargs[key] = bool(self.params[key])
            self._engine = cls(**kwargs)

        self._load_ms = (time.perf_counter() - t0) * 1000
        return self._engine

    def warmup(self) -> None:
        self._load()

    # ---- 推理 ----
    def _predict(self, req: EngineRequest) -> EngineOutput:
        engine = self._load()
        thresh = float(self.params.get("box_score_thresh", 0.0) or 0.0)

        with image_file(req) as path:
            size = image_size(path)
            t0 = time.perf_counter()
            if self._major >= 3:
                raw = engine.predict(path)
            else:
                raw = engine.ocr(path, cls=self.use_angle_cls)
            infer_ms = (time.perf_counter() - t0) * 1000

        triples = _flatten(raw)

        lines: list[Line] = []
        dropped = 0
        for box, text, score in triples:
            text = (text or "").strip()
            if not text:
                continue
            if thresh and score is not None and score < thresh:
                dropped += 1
                continue
            lines.append(Line(text=text, box=box, score=score))

        lines.sort(key=_reading_order)

        return EngineOutput(
            text=lines_to_text(lines),
            lines=lines,
            usage={"images": 1},
            raw=raw,
            meta={
                "engine": "paddleocr",
                "paddleocr_major": self._major,
                "lang": self.lang,
                "image_size": list(size) if size else None,
                "infer_ms": round(infer_ms, 2),
                "load_ms": round(self._load_ms, 2) if self._load_ms is not None else None,
                **({"dropped_low_score": dropped} if dropped else {}),
            },
        )


# --------------------------------------------------------------------------
# 解析辅助：2.x / 3.x 返回结构差异在这里吸收
# --------------------------------------------------------------------------
def _major_version(ver: str) -> int:
    try:
        return int(str(ver).split(".")[0])
    except (TypeError, ValueError):
        return 2


def _flatten(raw: Any) -> list[tuple[Box | None, str, float | None]]:
    out: list[tuple[Box | None, str, float | None]] = []
    for page in _as_list(raw):
        # 3.x：dict / 对象带 rec_texts
        texts = _get(page, "rec_texts")
        if texts is not None:
            polys = _get(page, "rec_polys")
            if polys is None:
                polys = _get(page, "dt_polys")
            scores = _get(page, "rec_scores") or []
            for i, txt in enumerate(_as_list(texts)):
                box = poly_to_box(_at(polys, i))
                score = _at(scores, i)
                out.append((box, str(txt), _to_float(score)))
            continue

        # 2.x：[[box, (text, score)], ...]
        items = _as_list(page)
        if _looks_like_item(items):
            items = [items]
        for item in items:
            parsed = _parse_v2_item(item)
            if parsed is not None:
                out.append(parsed)
    return out


def _parse_v2_item(item: Any) -> tuple[Box | None, str, float | None] | None:
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return None
    box = poly_to_box(item[0])
    payload = item[1]
    if isinstance(payload, (list, tuple)) and payload and isinstance(payload[0], str):
        text = payload[0]
        score = payload[1] if len(payload) > 1 else None
        return box, text, _to_float(score)
    if isinstance(payload, str):
        return box, payload, None
    if isinstance(item, dict):
        return poly_to_box(item.get("box")), str(item.get("text") or ""), _to_float(item.get("score"))
    return None


def _looks_like_item(items: list[Any]) -> bool:
    """判断 [box, (text, score)] 这种单条目是否被当成了条目列表。"""
    if len(items) != 2:
        return False
    first, second = items
    return (
        isinstance(first, (list, tuple))
        and isinstance(second, (list, tuple))
        and len(second) >= 1
        and isinstance(second[0], str)
    )


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    try:  # numpy 数组 / paddle Tensor
        return list(v)
    except TypeError:
        return [v]


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _at(seq: Any, i: int) -> Any:
    if seq is None:
        return None
    try:
        return seq[i]
    except (IndexError, KeyError, TypeError):
        return None


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _reading_order(line: Line) -> tuple[float, float]:
    if line.box is None:
        return (float("inf"), float("inf"))
    return ((line.box.y1 + line.box.y2) / 2, line.box.x1)
