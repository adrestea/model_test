"""测试用的假引擎：不依赖任何模型，只验证 runner/metrics 的编排逻辑。"""
from __future__ import annotations

import time
from typing import Any

from adapters.base import BaseEngine, register
from core.types import EngineOutput, EngineRequest


@register("test.echo")
class EchoEngine(BaseEngine):
    """按 params.outputs[sample_id] 返回文本，可配置延迟/首次失败。"""

    capabilities = ("recognize", "extract")
    modalities = ("image",)

    def __init__(
        self,
        engine_id: str,
        params: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
    ):
        self.calls = 0
        super().__init__(engine_id, params, cost)

    def _predict(self, req: EngineRequest) -> EngineOutput:
        self.calls += 1
        delay = float(self.params.get("delay_ms", 0) or 0) / 1000.0
        if delay > 0:
            time.sleep(delay)
        if self.calls <= int(self.params.get("fail_times", 0) or 0):
            raise RuntimeError(f"模拟第 {self.calls} 次调用失败")
        outputs = self.params.get("outputs") or {}
        text = str(outputs.get(req.sample_id, self.params.get("default_text", "")))
        return EngineOutput(text=text, usage={"calls": 1})


@register("test.video_only")
class VideoOnlyEngine(BaseEngine):
    """只支持视频的引擎，用于验证模态跳过逻辑。"""

    capabilities = ("recognize",)
    modalities = ("video",)

    def _predict(self, req: EngineRequest) -> EngineOutput:
        return EngineOutput(text="")
