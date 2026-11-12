"""本地 VLM：ollama / OpenAI 兼容端点 / transformers，三后端共用 ``vlm.local``。

``params.backend`` 选择后端，``params.device`` 默认 ``auto``：

- ``auto`` 按 **cuda -> mps -> cpu** 顺序探测（需要 torch 才能探测 GPU）；
- 显式 ``cpu`` / ``cuda`` / ``cuda:1`` / ``mps`` 原样使用；
- 探测结果写入 ``Prediction.meta.device_probe``，便于复现实验环境。

三个后端都惰性加载依赖：缺 ollama 服务、缺 torch/transformers 时只会在
``Prediction.error`` 里给出中文安装/启动提示，不会让整个 run 崩溃。
"""
from __future__ import annotations

import io
import threading
import time
from typing import Any

from adapters._http import post_json
from adapters._vlm_util import (
    append_schema,
    detect_device,
    device_meta,
    float_param,
    int_param,
    load_image,
    maybe_parse_fields,
    resolve_prompt,
    run_openai_compat,
    timeout_param,
    to_b64,
)
from adapters.base import BaseEngine, register
from core.types import EngineOutput, EngineRequest

SUPPORTED_BACKENDS = ("ollama", "openai_compat", "transformers")
_TRANSFORMERS_INSTALL_HINT = (
    "安装：`pip install torch transformers accelerate pillow`；"
    "GPU 机器请按 CUDA 版本安装 torch（https://pytorch.org/get-started/locally/）。"
)


@register("vlm.local")
class LocalVLMEngine(BaseEngine):
    capabilities = ("recognize", "vqa", "extract")
    modalities = ("image",)

    def __init__(self, engine_id: str, params: dict[str, Any] | None = None,
                 cost: dict[str, Any] | None = None):
        super().__init__(engine_id, params, cost)
        self._requested_device = str(self.params.get("device") or "auto").strip()
        self._resolved_device, self._device_probe = detect_device(self._requested_device)
        self._backend = str(self.params.get("backend") or "ollama").strip().lower()
        self._config_error: str | None = None
        self._backend_impl: _TransformersBackend | None = None
        if self._backend not in SUPPORTED_BACKENDS:
            self._config_error = (
                f"vlm.local[{self.engine_id}]: 不支持的 params.backend={self._backend!r}，"
                f"可选值: {' | '.join(SUPPORTED_BACKENDS)}"
            )
        elif self._backend == "transformers":
            self._backend_impl = _TransformersBackend(
                self.params, self._resolved_device, self._device_probe
            )

    @property
    def device(self) -> str:
        if self._backend_impl is not None:
            return self._backend_impl.device
        return self._resolved_device

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        info["backend"] = self._backend
        info["device_requested"] = self._requested_device
        return info

    def warmup(self) -> None:
        """transformers 后端可提前加载权重；加载失败留给 predict 报中文错误。"""
        if self._backend_impl is None:
            return
        try:
            self._backend_impl.ensure_model()
        except Exception:  # noqa: BLE001 - warmup 不阻断 run
            pass

    def _predict(self, req: EngineRequest) -> EngineOutput:
        if self._config_error:
            raise ValueError(self._config_error)
        model = str(self.params.get("model") or "").strip()
        if not model:
            raise ValueError(
                f"vlm.local[{self.engine_id}]: 缺少 params.model"
                "（ollama 示例 qwen2.5vl:3b；transformers 示例 Qwen/Qwen2.5-VL-3B-Instruct）"
            )
        if self._backend == "ollama":
            return self._predict_ollama(req, model)
        if self._backend == "openai_compat":
            return self._predict_openai_compat(req)
        assert self._backend_impl is not None
        out = self._backend_impl.predict(req)
        out.meta.update(device_meta(
            self._requested_device, self.device, self._device_probe
        ))
        return out

    # ------------------------------------------------------------ ollama
    def _ollama_url(self) -> str:
        endpoint = str(self.params.get("endpoint") or "").strip()
        if endpoint:
            return endpoint
        base = str(self.params.get("base_url") or "http://localhost:11434").strip().rstrip("/")
        if base.endswith("/api/chat"):
            return base
        if base.endswith("/api"):
            return f"{base}/chat"
        return f"{base}/api/chat"

    def _predict_ollama(self, req: EngineRequest, model: str) -> EngineOutput:
        label = f"vlm.local[ollama:{self.engine_id}]"
        params = self.params
        data, mime, source = load_image(req, params)
        prompt = append_schema(resolve_prompt(req, params), req.schema)

        options: dict[str, Any] = {
            "temperature": float_param(params, "temperature", 0.0),
            "num_predict": int_param(
                params, "max_new_tokens",
                int_param(params, "max_tokens", 2048),
            ),
        }
        custom_options = params.get("options")
        if isinstance(custom_options, dict):
            options.update(custom_options)

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [to_b64(data)],
            }],
            "stream": False,
            "options": options,
        }
        if params.get("keep_alive") is not None:
            payload["keep_alive"] = params["keep_alive"]
        extra = params.get("extra_body")
        if isinstance(extra, dict):
            payload.update(extra)

        headers = {"Content-Type": "application/json"}
        custom = params.get("headers")
        if isinstance(custom, dict):
            headers.update({str(k): str(v) for k, v in custom.items()})

        url = self._ollama_url()
        resp = post_json(
            url, payload, headers,
            timeout=timeout_param(params, default=600.0),
            engine_label=label,
        )
        error = resp.get("error")
        if isinstance(error, str) and error.strip():
            raise RuntimeError(
                f"{label}: ollama 返回错误: {error.strip()}。"
                f"请确认已执行 `ollama pull {model}` 且 `ollama serve` 正在运行"
                f"（{url}）。"
            )
        message = resp.get("message") if isinstance(resp.get("message"), dict) else {}
        text = str(message.get("content") or "").strip()
        if not text:
            raise RuntimeError(
                f"{label}: ollama 返回空文本（done_reason={resp.get('done_reason')}）；"
                f"请检查模型是否为多模态模型、prompt 是否正常。"
            )

        input_tokens = _as_int(resp.get("prompt_eval_count"))
        output_tokens = _as_int(resp.get("eval_count"))
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "images": 1,
            "calls": 1,
        }
        meta: dict[str, Any] = {
            "backend": "ollama",
            "model": model,
            "endpoint": url,
            "image_mime": mime,
            "image_bytes": len(data),
            "image_source": source,
            "done_reason": resp.get("done_reason"),
            "total_duration_ms": _ns_to_ms(resp.get("total_duration")),
            "load_duration_ms": _ns_to_ms(resp.get("load_duration")),
            "prompt_eval_duration_ms": _ns_to_ms(resp.get("prompt_eval_duration")),
            "eval_duration_ms": _ns_to_ms(resp.get("eval_duration")),
        }
        meta.update(device_meta(
            self._requested_device, self._resolved_device, self._device_probe
        ))
        return EngineOutput(
            text=text,
            fields=maybe_parse_fields(text, req.schema),
            raw=resp,
            usage=usage,
            meta=meta,
        )

    # ------------------------------------------------------------ openai_compat
    def _predict_openai_compat(self, req: EngineRequest) -> EngineOutput:
        label = f"vlm.local[openai_compat:{self.engine_id}]"
        params = dict(self.params)
        params.setdefault("base_url", "http://localhost:8000/v1")
        out = run_openai_compat(
            req, params,
            engine_label=label,
            require_key=False,
            default_base_url="http://localhost:8000/v1",
            default_key_env="LOCAL_VLM_API_KEY",
            default_max_tokens=2048,
        )
        out.meta["backend"] = "openai_compat"
        out.meta.update(device_meta(
            self._requested_device, self._resolved_device, self._device_probe
        ))
        return out


def _as_int(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _ns_to_ms(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) / 1e6, 2)
    except (TypeError, ValueError):
        return None


class _TransformersBackend:
    """transformers 后端：进程内加载模型，单实例 + 锁串行 generate。

    不在模块顶层 import torch/transformers，缺依赖时只在调用时抛中文错误。
    """

    def __init__(self, params: dict[str, Any], device: str,
                 probe: dict[str, Any]):
        self.params = params
        self.device = device
        self.device_probe = probe
        self.load_ms: float | None = None
        self.dtype_name: str | None = None
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self._lock = threading.Lock()

    def _deps(self) -> tuple[Any, Any, Any]:
        try:
            import torch
        except ImportError as e:
            raise RuntimeError(
                f"vlm.local[transformers]: 缺少依赖 torch，无法加载本地模型。"
                f"{_TRANSFORMERS_INSTALL_HINT}"
            ) from e
        try:
            import transformers
            from PIL import Image
        except ImportError as e:
            missing = getattr(e, "name", None) or "transformers/Pillow"
            raise RuntimeError(
                f"vlm.local[transformers]: 缺少依赖 {missing}，无法加载本地模型。"
                f"{_TRANSFORMERS_INSTALL_HINT}"
            ) from e
        return torch, transformers, Image

    def _dtype(self, torch: Any) -> Any:
        name = str(self.params.get("dtype") or self.params.get("torch_dtype")
                   or "auto").strip().lower()
        if name == "auto":
            if str(self.device).startswith(("cuda", "mps")):
                return torch.float16
            return torch.float32
        mapping = {
            "float16": torch.float16, "fp16": torch.float16,
            "bfloat16": torch.bfloat16, "bf16": torch.bfloat16,
            "float32": torch.float32, "fp32": torch.float32,
        }
        if name not in mapping:
            raise ValueError(
                f"vlm.local[transformers]: 不支持的 dtype={name!r}，"
                "可选 auto | float16 | bfloat16 | float32"
            )
        return mapping[name]

    def ensure_model(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            self._load_model()

    def _load_model(self) -> None:
        torch, transformers, _ = self._deps()
        model_name = str(self.params.get("model") or "").strip()
        common: dict[str, Any] = {}
        if self.params.get("trust_remote_code") is not None:
            common["trust_remote_code"] = bool(self.params["trust_remote_code"])
        if self.params.get("revision"):
            common["revision"] = str(self.params["revision"])
        if self.params.get("cache_dir"):
            common["cache_dir"] = str(self.params["cache_dir"])
        if self.params.get("local_files_only"):
            common["local_files_only"] = True

        started = time.perf_counter()
        try:
            processor = transformers.AutoProcessor.from_pretrained(model_name, **common)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"vlm.local[transformers]: 加载 processor 失败（model={model_name}）："
                f"{type(e).__name__}: {e}。请确认模型名/本地路径正确、HuggingFace 可访问；"
                "离线请先下载模型并设 params.local_files_only=true；"
                "部分模型还需 `pip install qwen-vl-utils timm`。"
            ) from e

        model_cls = None
        for attr in ("AutoModelForImageTextToText", "AutoModelForVision2Seq",
                     "AutoModelForCausalLM"):
            model_cls = getattr(transformers, attr, None)
            if model_cls is not None:
                break
        if model_cls is None:
            raise RuntimeError(
                "vlm.local[transformers]: 当前 transformers 版本过旧，缺少 "
                "AutoModelForImageTextToText / AutoModelForVision2Seq；"
                "请执行 `pip install -U transformers`。"
            )
        dtype = self._dtype(torch)
        try:
            model = model_cls.from_pretrained(
                model_name, torch_dtype=dtype, **common
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"vlm.local[transformers]: 加载模型失败（model={model_name}）："
                f"{type(e).__name__}: {e}。请确认权重完整、显存/内存足够；"
                "显存不足可换更小模型、设 params.dtype=bfloat16 或 device=cpu。"
            ) from e

        try:
            model.to(self.device)
        except Exception as e:  # noqa: BLE001
            if str(self.device) == "cpu":
                raise RuntimeError(
                    f"vlm.local[transformers]: 模型迁移到 CPU 失败：{e}"
                ) from e
            original = self.device
            self.device = "cpu"
            self.device_probe = {
                **self.device_probe,
                "reason": f"模型迁移到 {original} 失败（{type(e).__name__}: {e}），已回落 CPU",
                "fallback_from": original,
            }
            try:
                model.to("cpu")
            except Exception as e2:  # noqa: BLE001
                raise RuntimeError(
                    f"vlm.local[transformers]: 模型迁移到 {original} 与 CPU 均失败：{e2}"
                ) from e2
        model.eval()
        self._model = model
        self._processor = processor
        self._torch = torch
        self.dtype_name = str(dtype).replace("torch.", "")
        self.load_ms = round((time.perf_counter() - started) * 1000, 2)

    def _build_inputs(self, prompt: str, image: Any) -> dict[str, Any]:
        processor = self._processor
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }]
        template_text = None
        try:
            template_text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:  # noqa: BLE001 - 老模型没有 chat template，走纯文本拼接
            template_text = None
        try:
            if template_text:
                return processor(text=[template_text], images=[image],
                                 return_tensors="pt")
            return processor(text=prompt, images=image, return_tensors="pt")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"vlm.local[transformers]: 图片预处理失败（model="
                f"{self.params.get('model')}）：{type(e).__name__}: {e}。"
                "请确认该模型支持 AutoProcessor 图像输入；"
                "部分模型需要 params.trust_remote_code=true 或额外依赖"
                "（如 qwen-vl-utils）。"
            ) from e

    def predict(self, req: EngineRequest) -> EngineOutput:
        torch, _, Image = self._deps()
        self.ensure_model()
        data, mime, source = load_image(req, self.params)
        prompt = append_schema(resolve_prompt(req, self.params), req.schema)
        try:
            image = Image.open(io.BytesIO(data))
            if image.mode != "RGB":
                image = image.convert("RGB")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"vlm.local[transformers]: 无法解码图片（sample_id={req.sample_id}，"
                f"mime={mime}）：{type(e).__name__}: {e}"
            ) from e

        inputs = self._build_inputs(prompt, image)
        inputs = {
            k: (v.to(self.device) if hasattr(v, "to") else v)
            for k, v in inputs.items()
        }
        max_new_tokens = int_param(
            self.params, "max_new_tokens",
            int_param(self.params, "max_tokens", 2048),
        )
        generation: dict[str, Any] = dict(self.params.get("generation_kwargs") or {})
        generation.setdefault("max_new_tokens", max_new_tokens)
        temperature = float_param(self.params, "temperature", 0.0)
        do_sample = bool(self.params.get("do_sample", False)) or temperature > 0
        generation.setdefault("do_sample", do_sample)
        if do_sample:
            generation.setdefault("temperature", temperature)
            if self.params.get("top_p") is not None:
                generation.setdefault("top_p", float_param(self.params, "top_p", 1.0))

        try:
            with torch.inference_mode():
                generated = self._model.generate(**inputs, **generation)
        except Exception as e:  # noqa: BLE001
            text = str(e).lower()
            if "out of memory" in text or "OutOfMemory" in type(e).__name__:
                raise RuntimeError(
                    f"vlm.local[transformers]: 显存/内存不足（device={self.device}，"
                    f"model={self.params.get('model')}）。可减小 max_new_tokens、"
                    "设 params.dtype=bfloat16、降低图片分辨率或改用更小模型。"
                ) from e
            raise RuntimeError(
                f"vlm.local[transformers]: 生成失败（device={self.device}）："
                f"{type(e).__name__}: {e}"
            ) from e

        input_ids = inputs.get("input_ids")
        input_len = int(input_ids.shape[-1]) if hasattr(input_ids, "shape") else 0
        token_ids = generated[0][input_len:] if input_len else generated[0]
        try:
            text = self._processor.decode(
                token_ids, skip_special_tokens=True
            ).strip()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"vlm.local[transformers]: 解码生成结果失败：{type(e).__name__}: {e}"
            ) from e
        if not text:
            raise RuntimeError(
                "vlm.local[transformers]: 模型生成空文本；"
                "可调大 max_new_tokens 或检查 prompt / chat template。"
            )

        output_tokens = int(token_ids.shape[-1]) if hasattr(token_ids, "shape") else 0
        usage = {
            "input_tokens": input_len,
            "output_tokens": output_tokens,
            "total_tokens": input_len + output_tokens,
            "images": 1,
            "calls": 1,
        }
        meta: dict[str, Any] = {
            "backend": "transformers",
            "model": self.params.get("model"),
            "dtype": self.dtype_name,
            "load_ms": self.load_ms,
            "image_mime": mime,
            "image_bytes": len(data),
            "image_source": source,
            "max_new_tokens": max_new_tokens,
        }
        return EngineOutput(
            text=text,
            fields=maybe_parse_fields(text, req.schema),
            raw=None,
            usage=usage,
            meta=meta,
        )
