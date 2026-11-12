"""在线 VLM：任何 OpenAI 兼容的 ``/chat/completions`` 端点。

适用：DashScope 兼容模式（qwen-vl-max）、OpenAI（gpt-4o-mini）、
智谱（glm-4v-plus）、vLLM / LM Studio / llama.cpp 等。

关键参数（与 configs/full.yaml 对齐）::

    type: vlm.openai_compat
    params:
      base_url: https://api.openai.com/v1   # 必填
      model: gpt-4o-mini                    # 必填
      api_key_env: OPENAI_API_KEY           # 环境变量名，默认 OPENAI_API_KEY
      max_tokens: 4096                      # 亦可用 max_new_tokens
      temperature: 0                        # 默认 0，保证可复现
      prompt: ... / prompt_file: ...        # 默认 core.config.DEFAULT_PROMPT
      image_detail: high                    # 可选 auto|low|high
      timeout_s: 120

缺 key / 缺图 / 非 2xx / 空响应都会抛中文异常，由 BaseEngine.predict 记录到
``Prediction.error``，不会中断整个评测 run。
"""
from __future__ import annotations

from adapters._vlm_util import run_openai_compat
from adapters.base import BaseEngine, register
from core.types import EngineOutput, EngineRequest


@register("vlm.openai_compat")
class OpenAICompatVLM(BaseEngine):
    capabilities = ("recognize", "vqa", "extract")
    modalities = ("image",)

    @property
    def device(self) -> str:
        # 远程 API 没有本地 device 概念；显式配置时尊重配置。
        return str(self.params.get("device") or "remote")

    def _predict(self, req: EngineRequest) -> EngineOutput:
        label = f"vlm.openai_compat[{self.engine_id}]"
        return run_openai_compat(
            req, self.params,
            engine_label=label,
            require_key=True,
            default_key_env="OPENAI_API_KEY",
        )
