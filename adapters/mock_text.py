"""mock.text：管线自检用的假引擎，不代表任何真实 OCR / VLM 能力。

用途：在没有模型依赖的 CPU 环境里验证 metrics → runner → CLI → baseline 全链路。
输出从 `params.mock_dir` 下读取同名 `<sample_id>.json` / `<sample_id>.txt`：
  - json: {"text": "...", "lines": [{"text": "...", "box": [x1,y1,x2,y2]}], "fields": {...}}
  - txt : 纯文本，按行切成 lines（无 box）
找不到文件则返回 `default_text`（默认空串），可用来模拟"完全漏提"。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from adapters.base import BaseEngine, register
from core.types import Box, EngineOutput, EngineRequest, Line


@register("mock.text")
class MockTextEngine(BaseEngine):
    type_name = "mock.text"
    capabilities = ("recognize", "extract", "vqa")
    modalities = ("image",)

    def _validate(self) -> None:
        mock_dir = self.params.get("mock_dir")
        if mock_dir and not Path(mock_dir).is_dir():
            raise FileNotFoundError(f"mock_dir 不存在: {mock_dir}")

    def _predict(self, req: EngineRequest) -> EngineOutput:
        delay = float(self.params.get("delay_ms", 0) or 0) / 1000.0
        if delay > 0:
            time.sleep(delay)

        if self.params.get("fail"):
            raise RuntimeError("mock.text 按参数要求失败")

        text = str(self.params.get("default_text", ""))
        lines: list[Line] | None = None
        fields: dict | None = None

        mock_dir = self.params.get("mock_dir")
        if mock_dir:
            base = Path(mock_dir) / req.sample_id
            js = base.with_suffix(".json")
            txt = base.with_suffix(".txt")
            if js.is_file():
                payload = json.loads(js.read_text(encoding="utf-8"))
                text = str(payload.get("text") or "")
                if payload.get("lines"):
                    lines = [
                        Line(
                            text=str(item.get("text", "")),
                            box=Box.from_any(item.get("box")),
                            score=item.get("score"),
                        )
                        for item in payload["lines"]
                    ]
                fields = payload.get("fields")
            elif txt.is_file():
                text = txt.read_text(encoding="utf-8")

        return EngineOutput(
            text=text,
            lines=lines,
            fields=fields,
            usage={"calls": 1, "images": 1},
            meta={"mock": True},
        )
