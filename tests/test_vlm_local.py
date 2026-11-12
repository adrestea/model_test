"""vlm.local：ollama / openai_compat / transformers 三后端 + device 探测。"""
from __future__ import annotations

import base64
import importlib.util

import pytest

from adapters._vlm_util import detect_device
from adapters.base import build_engine
from core.types import EngineRequest
from tests.test_vlm_http_stub import PNG_BYTES, StubServer

OLLAMA_OK = {
    "model": "qwen2.5vl:3b",
    "message": {"role": "assistant", "content": "本地识别：合计 ¥128.00"},
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 88,
    "eval_count": 17,
    "total_duration": 1234567890,
    "load_duration": 4567890,
    "prompt_eval_duration": 300000000,
    "eval_duration": 900000000,
}


def _ollama_ok(record):
    return 200, OLLAMA_OK, None


def _engine(**params):
    params = {"backend": "ollama", "model": "qwen2.5vl:3b",
              "device": "auto", "max_new_tokens": 2048, **params}
    return build_engine({
        "id": "local-qwen25vl-3b", "type": "vlm.local",
        "params": params, "cost": {"per_image": 0},
    })


def _req(**kw):
    kw.setdefault("sample_id", "l1")
    kw.setdefault("task", "recognize")
    kw.setdefault("media_bytes", PNG_BYTES)
    return EngineRequest(**kw)


def test_ollama_request_and_usage():
    with StubServer(_ollama_ok) as srv:
        pred = _engine(base_url=srv.base_url).predict(_req())

    assert pred.ok, pred.error
    assert pred.text == "本地识别：合计 ¥128.00"
    assert pred.usage["input_tokens"] == 88
    assert pred.usage["output_tokens"] == 17
    assert pred.usage["total_tokens"] == 105
    assert pred.usage["images"] == 1
    assert pred.meta["backend"] == "ollama"
    assert pred.meta["model"] == "qwen2.5vl:3b"
    assert pred.meta["device"] in ("cpu", "cuda", "mps")
    assert pred.meta["device_requested"] == "auto"
    assert "device_probe" in pred.meta
    assert pred.meta["total_duration_ms"] == 1234.57

    rec = srv.records[0]
    assert rec["path"] == "/api/chat"
    body = rec["body"]
    assert body["model"] == "qwen2.5vl:3b"
    assert body["stream"] is False
    message = body["messages"][0]
    assert message["role"] == "user"
    assert "OCR 引擎" in message["content"]
    assert base64.b64decode(message["images"][0]) == PNG_BYTES
    assert body["options"]["num_predict"] == 2048
    assert body["options"]["temperature"] == 0.0
    assert "authorization" not in rec["headers"]


def test_ollama_base_url_with_api_suffix():
    with StubServer(_ollama_ok) as srv:
        pred = _engine(base_url=f"{srv.base_url}/api").predict(_req())
    assert pred.ok, pred.error
    assert srv.records[0]["path"] == "/api/chat"


def test_ollama_error_field_is_reported():
    def responder(record):
        return 200, {"error": "model 'qwen2.5vl:3b' not found"}, None

    with StubServer(responder) as srv:
        pred = _engine(base_url=srv.base_url).predict(_req())
    assert not pred.ok
    assert "not found" in pred.error
    assert "ollama pull" in pred.error
    assert "ollama serve" in pred.error


def test_ollama_connection_refused_message():
    pred = _engine(base_url="http://127.0.0.1:1", timeout_s=2).predict(_req())
    assert not pred.ok
    assert "无法连接" in pred.error
    assert "ollama serve" in pred.error


def test_local_openai_compat_backend_without_key():
    def responder(record):
        return 200, {
            "choices": [{"message": {"content": "vLLM 本地结果"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                      "total_tokens": 15},
        }, None

    with StubServer(responder) as srv:
        pred = _engine(backend="openai_compat",
                       base_url=f"{srv.base_url}/v1").predict(_req())
    assert pred.ok, pred.error
    assert pred.text == "vLLM 本地结果"
    assert pred.usage["input_tokens"] == 10
    assert pred.usage["output_tokens"] == 5
    assert pred.meta["backend"] == "openai_compat"
    rec = srv.records[0]
    assert rec["path"] == "/v1/chat/completions"
    assert "authorization" not in rec["headers"]   # 本地服务默认无 key
    image = rec["body"]["messages"][0]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,")


def test_local_openai_compat_uses_max_new_tokens():
    sent = {}

    def responder(record):
        sent.update(record["body"])
        return 200, {"choices": [{"message": {"content": "ok"},
                                  "finish_reason": "stop"}]}, None

    with StubServer(responder) as srv:
        pred = _engine(backend="openai_compat", base_url=f"{srv.base_url}/v1",
                       max_new_tokens=777).predict(_req())
    assert pred.ok, pred.error
    assert sent["max_tokens"] == 777


def test_local_unknown_backend_is_clear_and_no_request():
    with StubServer(_ollama_ok) as srv:
        pred = _engine(backend="vllm", base_url=srv.base_url).predict(_req())
    assert not pred.ok
    assert "不支持的 params.backend" in pred.error
    assert "ollama | openai_compat | transformers" in pred.error
    assert srv.records == []


def test_local_missing_model():
    eng = build_engine({"id": "local", "type": "vlm.local",
                        "params": {"backend": "ollama"}})
    pred = eng.predict(_req())
    assert not pred.ok
    assert "缺少 params.model" in pred.error


@pytest.mark.skipif(importlib.util.find_spec("torch") is not None,
                    reason="torch 已安装，跳过缺依赖用例")
def test_transformers_missing_dependency_message():
    eng = _engine(backend="transformers", model="Qwen/Qwen2.5-VL-3B-Instruct")
    # warmup 不允许把整个 run 带崩
    assert eng.warmup() is None
    pred = eng.predict(_req())
    assert not pred.ok
    assert "缺少依赖 torch" in pred.error
    assert "pip install torch transformers accelerate pillow" in pred.error


def test_transformer_backend_not_imported_eagerly():
    # 只构造引擎不应 import torch/transformers，也不应发网络请求
    eng = _engine(backend="transformers", model="Qwen/Qwen2.5-VL-3B-Instruct")
    assert eng.describe()["backend"] == "transformers"
    assert eng.device in ("cpu", "cuda", "mps")


def test_device_probe_auto():
    resolved, info = detect_device("auto")
    assert resolved in ("cpu", "cuda", "mps")
    assert info["requested"] == "auto"
    for key in ("torch_available", "cuda_available", "mps_available", "reason"):
        assert key in info
    if not info["torch_available"]:
        assert resolved == "cpu"
        assert "torch" in info["reason"]


def test_device_explicit_passthrough():
    for value in ("cpu", "cuda", "cuda:1", "mps"):
        resolved, info = detect_device(value)
        assert resolved == value
        assert info["requested"] == value


def test_local_engine_meta_contains_probe():
    with StubServer(_ollama_ok) as srv:
        pred = _engine(base_url=srv.base_url, device="cpu").predict(_req())
    assert pred.ok, pred.error
    assert pred.meta["device"] == "cpu"
    assert pred.meta["device_requested"] == "cpu"
    assert pred.meta["device_probe"]["requested"] == "cpu"


def test_local_prompt_and_temperature_override():
    with StubServer(_ollama_ok) as srv:
        pred = _engine(base_url=srv.base_url, prompt="只输出金额",
                       temperature=0.2).predict(_req())
    assert pred.ok, pred.error
    body = srv.records[0]["body"]
    assert body["messages"][0]["content"] == "只输出金额"
    assert body["options"]["temperature"] == 0.2
