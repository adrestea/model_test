"""VLM adapter 共享的私有工具：图片编码、prompt、响应解析、device 探测。

不注册引擎，不 import 任何模型 SDK 的重型依赖（torch/transformers 只在
真正调用本地 transformers 后端时才 import），因此本模块可以安全地被
``load_builtin_adapters()`` 导入。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from adapters._http import (
    DEFAULT_TIMEOUT_S,
    key_env_name,
    post_json,
    resolve_api_key,
)
from core.config import DEFAULT_PROMPT
from core.types import EngineOutput, EngineRequest

DEFAULT_MAX_TOKENS = 4096
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)
_VALID_DETAILS = ("auto", "low", "high")


# ---------------------------------------------------------------- 参数解析

def int_param(params: dict[str, Any], key: str, default: int = 0) -> int:
    """读取整型参数；非法值直接抛中文配置错误，避免悄悄用错参数。"""
    raw = params.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"参数 {key} 必须是整数，当前值: {raw!r}（引擎参数写错了）") from e


def float_param(params: dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = params.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"参数 {key} 必须是数字，当前值: {raw!r}（引擎参数写错了）") from e


def timeout_param(params: dict[str, Any], default: float = DEFAULT_TIMEOUT_S) -> float:
    raw = params.get("timeout_s")
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"参数 timeout_s 必须是数字，当前值: {raw!r}") from e
    return value if value > 0 else default


def max_tokens_param(params: dict[str, Any], default: int) -> int:
    """在线用 max_tokens，本地用 max_new_tokens；两者都支持，前者优先。"""
    if params.get("max_tokens") is not None:
        return int_param(params, "max_tokens", default)
    return int_param(params, "max_new_tokens", default)


# ---------------------------------------------------------------- 图片

def sniff_mime(data: bytes, path: str | Path | None = None) -> str:
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if path:
        guessed, _ = mimetypes.guess_type(str(path))
        if guessed and guessed.startswith("image/"):
            return guessed
    return "image/jpeg"


def load_image(req: EngineRequest, params: dict[str, Any]) -> tuple[bytes, str, str]:
    """返回 (原始字节, MIME, 来源描述)。media_bytes 优先于 media_path。"""
    path: str | Path | None = None
    if req.media_bytes is not None:
        data = bytes(req.media_bytes)
        source = "media_bytes"
    else:
        raw_path = req.media_path or params.get("image_path")
        if not raw_path:
            raise ValueError(
                f"请求未提供图片：media_path / media_bytes 均为空"
                f"（sample_id={req.sample_id}）。请检查数据集样本与 runner 传参。"
            )
        path = Path(str(raw_path)).expanduser()
        if not path.is_file():
            raise FileNotFoundError(
                f"图片文件不存在: {path}（sample_id={req.sample_id}）"
            )
        data = path.read_bytes()
        source = str(path)
    if not data:
        raise ValueError(f"图片内容为空（sample_id={req.sample_id}，来源={source}）")
    mime = str(params.get("image_mime") or sniff_mime(data, path))
    return data, mime, source


def to_data_uri(data: bytes, mime: str) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def to_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------- Prompt

def resolve_prompt(req: EngineRequest, params: dict[str, Any]) -> str:
    """优先级：req.prompt > params.prompt > params.prompt_file > DEFAULT_PROMPT。"""
    if req.prompt and str(req.prompt).strip():
        return str(req.prompt).strip()
    if params.get("prompt") and str(params["prompt"]).strip():
        return str(params["prompt"]).strip()
    prompt_file = params.get("prompt_file") or params.get("prompt_path")
    if prompt_file:
        p = Path(str(prompt_file)).expanduser()
        if not p.is_file():
            raise FileNotFoundError(
                f"prompt_file 不存在: {p}。请检查引擎 params.prompt_file 路径。"
            )
        text = p.read_text(encoding="utf-8").strip()
        if text:
            return text
    return DEFAULT_PROMPT


def append_schema(prompt: str, schema: dict | None) -> str:
    """extract 任务把 JSON Schema 追加到 prompt，要求只输出 JSON。"""
    if not schema:
        return prompt
    schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    return (
        f"{prompt}\n\n"
        "请严格按以下 JSON Schema 输出字段抽取结果，只输出一个 JSON 对象，"
        f"不要输出解释、Markdown 代码块或任何额外文字：\n{schema_text}"
    )


# ---------------------------------------------------------------- OpenAI 兼容

def build_openai_messages(prompt: str, data: bytes, mime: str,
                          params: dict[str, Any]) -> list[dict[str, Any]]:
    image_url: dict[str, Any] = {"url": to_data_uri(data, mime)}
    detail = str(params.get("image_detail") or "").strip().lower()
    if detail in _VALID_DETAILS:
        image_url["detail"] = detail
    user_content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": image_url},
    ]
    messages: list[dict[str, Any]] = []
    system = params.get("system")
    if isinstance(system, str) and system.strip():
        messages.append({"role": "system", "content": system.strip()})
    messages.append({"role": "user", "content": user_content})
    return messages


def build_openai_payload(model: str, messages: list[dict[str, Any]],
                         params: dict[str, Any], default_max_tokens: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float_param(params, "temperature", 0.0),
        "stream": False,
    }
    max_tokens = max_tokens_param(params, default_max_tokens)
    field = str(params.get("max_tokens_field") or "max_tokens")
    if max_tokens > 0:
        payload[field] = max_tokens
    if params.get("top_p") is not None:
        payload["top_p"] = float_param(params, "top_p", 1.0)
    if params.get("seed") is not None:
        payload["seed"] = int_param(params, "seed", 0)
    for key in ("stop", "response_format", "presence_penalty", "frequency_penalty"):
        if params.get(key) is not None:
            payload[key] = params[key]
    extra = params.get("extra_body")
    if isinstance(extra, dict):
        payload.update(extra)
    return payload


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
                elif part.get("type") == "text" and isinstance(part.get("content"), str):
                    chunks.append(part["content"])
        return "\n".join(chunks)
    return ""


def _preview(obj: Any, limit: int = 300) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(obj)
    return text[:limit] + ("…" if len(text) > limit else "")


def extract_openai_text(resp: dict[str, Any], label: str) -> tuple[str, str | None]:
    """返回 (文本, finish_reason)；空文本/截断/结构异常都抛中文错误。"""
    choices = resp.get("choices")
    if not isinstance(choices, list) or not choices:
        err = resp.get("error")
        extra = f"；error={_preview(err)}" if err else ""
        raise RuntimeError(
            f"{label}: 响应中没有 choices，无法取文本{extra}；响应片段={_preview(resp)}"
        )
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    text = _content_to_text(message.get("content")).strip()
    finish = choice.get("finish_reason")
    if not text:
        if finish in ("length", "max_tokens"):
            raise RuntimeError(
                f"{label}: 输出被截断（finish_reason={finish}），"
                "请调大 params.max_tokens 后重试。"
            )
        raise RuntimeError(
            f"{label}: 模型返回空文本（finish_reason={finish}）；"
            f"响应片段={_preview(choice)}"
        )
    return text, finish


def parse_openai_usage(resp: dict[str, Any]) -> dict[str, int]:
    usage = resp.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    prompt = _int(usage.get("prompt_tokens", usage.get("input_tokens")))
    completion = _int(usage.get("completion_tokens", usage.get("output_tokens")))
    total = _int(usage.get("total_tokens")) or (prompt + completion)
    out: dict[str, int] = {
        "input_tokens": prompt,
        "output_tokens": completion,
        "total_tokens": total,
        "images": 1,
        "calls": 1,
    }
    cached = _nested_int(usage, "prompt_tokens_details", "cached_tokens")
    if cached:
        out["cached_input_tokens"] = cached
    reasoning = _nested_int(usage, "completion_tokens_details", "reasoning_tokens")
    if reasoning:
        out["reasoning_tokens"] = reasoning
    return out


def extract_gemini_text(resp: dict[str, Any], label: str) -> tuple[str, str | None]:
    candidates = resp.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = resp.get("promptFeedback")
        reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
        if reason:
            raise RuntimeError(
                f"{label}: 请求被 Gemini 安全策略拒绝（blockReason={reason}）。"
                "请更换图片内容，或通过 params.safety_settings 调整过滤阈值。"
            )
        raise RuntimeError(
            f"{label}: 响应中没有 candidates；响应片段={_preview(resp)}"
        )
    cand = candidates[0] if isinstance(candidates[0], dict) else {}
    content = cand.get("content") if isinstance(cand.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    text = "".join(
        part.get("text", "") for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()
    finish = cand.get("finishReason")
    if not text:
        if finish == "MAX_TOKENS":
            raise RuntimeError(
                f"{label}: Gemini 输出被截断（finishReason=MAX_TOKENS），"
                "请调大 params.max_tokens。"
            )
        if finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise RuntimeError(
                f"{label}: Gemini 因安全策略未返回文本（finishReason={finish}）。"
            )
        raise RuntimeError(
            f"{label}: Gemini 返回空文本（finishReason={finish}）；"
            f"响应片段={_preview(cand)}"
        )
    return text, finish


def parse_gemini_usage(resp: dict[str, Any]) -> dict[str, int]:
    meta = resp.get("usageMetadata")
    if not isinstance(meta, dict):
        meta = {}
    prompt = _int(meta.get("promptTokenCount"))
    completion = _int(meta.get("candidatesTokenCount"))
    total = _int(meta.get("totalTokenCount")) or (prompt + completion)
    out: dict[str, int] = {
        "input_tokens": prompt,
        "output_tokens": completion,
        "total_tokens": total,
        "images": 1,
        "calls": 1,
    }
    thoughts = _int(meta.get("thoughtsTokenCount"))
    if thoughts:
        out["reasoning_tokens"] = thoughts
    cached = _int(meta.get("cachedContentTokenCount"))
    if cached:
        out["cached_input_tokens"] = cached
    return out


def _int(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _nested_int(obj: dict[str, Any], *keys: str) -> int:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return 0
        cur = cur.get(key)
    return _int(cur)


def maybe_parse_fields(text: str, schema: dict | None) -> dict[str, Any] | None:
    """extract 任务：尽量从文本里抠出 JSON 对象；失败返回 None（保留原文）。"""
    if not schema:
        return None
    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        candidates.append(fenced.group(1))
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"): text.rindex("}") + 1])
    candidates.append(text)
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


# ---------------------------------------------------------------- device 探测

def detect_device(pref: str | None = None) -> tuple[str, dict[str, Any]]:
    """解析 params.device。

    - 显式值（cpu / cuda / cuda:1 / mps）原样返回，不做可用性校验；
    - ``auto``（默认）按 cuda -> mps -> cpu 顺序探测；
    - torch 未安装时无法探测，直接回落 cpu 并在 reason 里说明。
    """
    raw = str(pref or "auto").strip().lower()
    info: dict[str, Any] = {
        "requested": raw or "auto",
        "torch_available": False,
        "cuda_available": False,
        "mps_available": False,
        "reason": "",
    }
    if raw not in ("", "auto", "gpu"):
        info["reason"] = "显式指定 device，跳过自动探测"
        return raw, info

    try:
        import torch
    except Exception as e:  # noqa: BLE001 - ImportError / 动态库加载失败都算不可用
        info["reason"] = f"torch 不可用（{type(e).__name__}: {e}），无法探测 GPU，回落 CPU"
        return "cpu", info

    info["torch_available"] = True
    try:
        if torch.cuda.is_available():
            info["cuda_available"] = True
            info["reason"] = "检测到 CUDA，使用 cuda"
            return "cuda", info
    except Exception as e:  # noqa: BLE001
        info["reason"] = f"CUDA 探测异常（{type(e).__name__}: {e}），继续尝试 MPS"
    try:
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        if mps is not None and mps.is_available():
            info["mps_available"] = True
            info["reason"] = "未检测到 CUDA，检测到 Apple MPS，使用 mps"
            return "mps", info
    except Exception as e:  # noqa: BLE001
        info["reason"] = f"MPS 探测异常（{type(e).__name__}: {e}），回落 CPU"
    if not info["reason"]:
        info["reason"] = "未检测到 CUDA/MPS，回落 CPU"
    return "cpu", info


def device_meta(pref: str | None, resolved: str,
                probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "device": resolved,
        "device_requested": str(pref or "auto"),
        "device_probe": probe,
    }


# ---------------------------------------------------------------- OpenAI 兼容调用

def run_openai_compat(
    req: EngineRequest,
    params: dict[str, Any],
    *,
    engine_label: str,
    require_key: bool = True,
    default_base_url: str | None = None,
    default_key_env: str = "OPENAI_API_KEY",
    default_max_tokens: int = DEFAULT_MAX_TOKENS,
) -> EngineOutput:
    """调用 ``POST {base_url}/chat/completions``，在线/本地共用的唯一实现。"""
    model = str(params.get("model") or "").strip()
    if not model:
        raise ValueError(
            f"{engine_label}: 缺少 params.model（例如 qwen-vl-max / gpt-4o-mini）。"
        )
    base_url = str(params.get("base_url") or default_base_url or "").strip()
    if not base_url:
        raise ValueError(
            f"{engine_label}: 缺少 params.base_url（OpenAI 兼容端点根地址，"
            "如 https://api.openai.com/v1）。"
        )
    if "://" not in base_url:
        raise ValueError(
            f"{engine_label}: params.base_url 必须以 http:// 或 https:// 开头，"
            f"当前值: {base_url!r}"
        )

    key_env = key_env_name(params, default_key_env)
    api_key = resolve_api_key(params, default_key_env, required=require_key,
                              engine_label=engine_label)
    data, mime, source = load_image(req, params)
    prompt = append_schema(resolve_prompt(req, params), req.schema)
    messages = build_openai_messages(prompt, data, mime, params)
    payload = build_openai_payload(model, messages, params, default_max_tokens)

    endpoint = str(params.get("endpoint") or "").strip()
    if endpoint:
        url = endpoint
    else:
        root = base_url.rstrip("/")
        # 允许 base_url 直接写成完整端点，避免拼出 .../chat/completions/chat/completions
        url = root if root.endswith("/chat/completions") else f"{root}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    custom = params.get("headers")
    if isinstance(custom, dict):
        headers.update({str(k): str(v) for k, v in custom.items()})

    resp = post_json(
        url, payload, headers,
        timeout=timeout_param(params),
        engine_label=engine_label,
        api_key_env=key_env,
    )
    text, finish = extract_openai_text(resp, engine_label)
    usage = parse_openai_usage(resp)
    meta: dict[str, Any] = {
        "backend": "openai_compat",
        "model": model,
        "endpoint": url,
        "image_mime": mime,
        "image_bytes": len(data),
        "image_source": source,
        "finish_reason": finish,
    }
    if resp.get("id"):
        meta["response_id"] = resp.get("id")
    return EngineOutput(
        text=text,
        fields=maybe_parse_fields(text, req.schema),
        raw=resp,
        usage=usage,
        meta=meta,
    )
