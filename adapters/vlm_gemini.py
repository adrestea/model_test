"""在线 VLM：Google Gemini ``generateContent`` REST API。

参数（与 configs/full.yaml 对齐）::

    type: vlm.gemini
    params:
      model: gemini-2.0-flash          # 必填
      api_key_env: GEMINI_API_KEY      # 默认 GEMINI_API_KEY
      max_tokens: 4096                 # -> generationConfig.maxOutputTokens
      temperature: 0
      base_url: https://generativelanguage.googleapis.com/v1beta  # 测试可覆盖
      endpoint: ...                    # 完整 URL，覆盖 base_url 拼接
      safety_settings: [...]           # 可选，原样透传

密钥通过 ``x-goog-api-key`` 请求头发送，不拼进 URL，避免出现在日志里。
"""
from __future__ import annotations

import base64
from typing import Any

from adapters._http import key_env_name, post_json, resolve_api_key
from adapters._vlm_util import (
    DEFAULT_MAX_TOKENS,
    append_schema,
    extract_gemini_text,
    float_param,
    int_param,
    load_image,
    maybe_parse_fields,
    max_tokens_param,
    parse_gemini_usage,
    resolve_prompt,
    timeout_param,
)
from adapters.base import BaseEngine, register
from core.types import EngineOutput, EngineRequest

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_KEY_ENV = "GEMINI_API_KEY"


@register("vlm.gemini")
class GeminiVLM(BaseEngine):
    capabilities = ("recognize", "vqa", "extract")
    modalities = ("image",)

    @property
    def device(self) -> str:
        return str(self.params.get("device") or "remote")

    def _endpoint(self, model: str) -> str:
        endpoint = str(self.params.get("endpoint") or "").strip()
        if endpoint:
            return endpoint
        base = str(self.params.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
        if ":generateContent" in base:
            return base
        # 兼容 model 写成 "models/gemini-2.0-flash" 的情况，避免拼出 /models/models/
        model_path = model[len("models/"):] if model.startswith("models/") else model
        if base.endswith("/models"):
            return f"{base}/{model_path}:generateContent"
        return f"{base}/models/{model_path}:generateContent"

    def _predict(self, req: EngineRequest) -> EngineOutput:
        label = f"vlm.gemini[{self.engine_id}]"
        params = self.params
        model = str(params.get("model") or "").strip()
        if not model:
            raise ValueError(f"{label}: 缺少 params.model（例如 gemini-2.0-flash）")

        key_env = key_env_name(params, DEFAULT_KEY_ENV)
        api_key = resolve_api_key(params, DEFAULT_KEY_ENV, required=True,
                                  engine_label=label)
        data, mime, source = load_image(req, params)
        prompt = append_schema(resolve_prompt(req, params), req.schema)

        payload: dict[str, Any] = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {
                        "mime_type": mime,
                        "data": base64.b64encode(data).decode("ascii"),
                    }},
                ],
            }],
        }
        generation: dict[str, Any] = {
            "temperature": float_param(params, "temperature", 0.0),
        }
        max_tokens = max_tokens_param(params, DEFAULT_MAX_TOKENS)
        if max_tokens > 0:
            generation["maxOutputTokens"] = max_tokens
        if params.get("top_p") is not None:
            generation["topP"] = float_param(params, "top_p", 1.0)
        if params.get("top_k") is not None:
            generation["topK"] = int_param(params, "top_k", 0)
        if params.get("response_mime_type"):
            generation["responseMimeType"] = str(params["response_mime_type"])
        if isinstance(params.get("stop_sequences"), (list, tuple)):
            generation["stopSequences"] = [str(v) for v in params["stop_sequences"]]
        payload["generationConfig"] = generation

        system = params.get("system")
        if isinstance(system, str) and system.strip():
            payload["systemInstruction"] = {"parts": [{"text": system.strip()}]}
        if isinstance(params.get("safety_settings"), list):
            payload["safetySettings"] = params["safety_settings"]

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key or "",
        }
        custom = params.get("headers")
        if isinstance(custom, dict):
            headers.update({str(k): str(v) for k, v in custom.items()})

        url = self._endpoint(model)
        resp = post_json(
            url, payload, headers,
            timeout=timeout_param(params),
            engine_label=label,
            api_key_env=key_env,
        )
        text, finish = extract_gemini_text(resp, label)
        usage = parse_gemini_usage(resp)
        meta = {
            "backend": "gemini",
            "model": model,
            "endpoint": url,
            "image_mime": mime,
            "image_bytes": len(data),
            "image_source": source,
            "finish_reason": finish,
        }
        return EngineOutput(
            text=text,
            fields=maybe_parse_fields(text, req.schema),
            raw=resp,
            usage=usage,
            meta=meta,
        )
