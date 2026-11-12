"""vlm.gemini：generateContent 请求构造 / usage / 安全拦截（本地假端点）。"""
from __future__ import annotations

import base64

from adapters.base import build_engine
from core.config import DEFAULT_PROMPT
from core.types import EngineRequest
from tests.test_vlm_http_stub import PNG_BYTES, StubServer

KEY_ENV = "VEVAL_TEST_GEMINI_KEY"


def _ok(text="发票金额：¥99.50", usage=None):
    def responder(record):
        return 200, {
            "candidates": [{
                "content": {"parts": [{"text": text}], "role": "model"},
                "finishReason": "STOP",
            }],
            "usageMetadata": usage if usage is not None else {
                "promptTokenCount": 200,
                "candidatesTokenCount": 42,
                "totalTokenCount": 242,
            },
            "modelVersion": "gemini-2.0-flash",
        }, None
    return responder


def _engine(base_url, **params):
    params = {"base_url": f"{base_url}/v1beta",
              "model": "gemini-2.0-flash",
              "api_key_env": KEY_ENV,
              **params}
    return build_engine({
        "id": "gemini", "type": "vlm.gemini", "params": params,
        "cost": {"input_per_1m": 0.1, "output_per_1m": 0.4},
    })


def _req(**kw):
    kw.setdefault("sample_id", "g1")
    kw.setdefault("task", "recognize")
    kw.setdefault("media_bytes", PNG_BYTES)
    return EngineRequest(**kw)


def test_gemini_request_usage_and_cost(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "gemini-key")
    with StubServer(_ok()) as srv:
        pred = _engine(srv.base_url, max_tokens=4096, image_detail="low").predict(_req())

    assert pred.ok, pred.error
    assert pred.text == "发票金额：¥99.50"
    assert pred.usage["input_tokens"] == 200
    assert pred.usage["output_tokens"] == 42
    assert pred.usage["total_tokens"] == 242
    assert pred.cost_usd == (200 / 1e6 * 0.1) + (42 / 1e6 * 0.4)
    assert pred.meta["type"] == "vlm.gemini"
    assert pred.meta["device"] == "remote"

    rec = srv.records[0]
    assert rec["path"] == "/v1beta/models/gemini-2.0-flash:generateContent"
    assert rec["headers"]["x-goog-api-key"] == "gemini-key"
    body = rec["body"]
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": DEFAULT_PROMPT}
    inline = parts[1]["inline_data"]
    assert inline["mime_type"] == "image/png"
    assert base64.b64decode(inline["data"]) == PNG_BYTES
    assert body["generationConfig"] == {
        "temperature": 0.0, "maxOutputTokens": 4096,
    }


def test_gemini_default_api_key_env_name(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-default-env")
    with StubServer(_ok()) as srv:
        eng = build_engine({
            "id": "gemini", "type": "vlm.gemini",
            "params": {"base_url": f"{srv.base_url}/v1beta",
                       "model": "gemini-2.0-flash"},
        })
        pred = eng.predict(_req())
    assert pred.ok, pred.error
    assert srv.records[0]["headers"]["x-goog-api-key"] == "from-default-env"


def test_gemini_endpoint_override(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")
    with StubServer(_ok()) as srv:
        eng = _engine(srv.base_url, endpoint=f"{srv.base_url}/custom/generate")
        assert eng.predict(_req()).ok
    assert srv.records[0]["path"] == "/custom/generate"


def test_gemini_blocked_by_safety(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")

    def responder(record):
        return 200, {"promptFeedback": {"blockReason": "SAFETY"}}, None

    with StubServer(responder) as srv:
        pred = _engine(srv.base_url).predict(_req())
    assert not pred.ok
    assert "SAFETY" in pred.error
    assert "安全策略" in pred.error


def test_gemini_finish_reason_safety(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")

    def responder(record):
        return 200, {"candidates": [{"content": {"parts": []},
                                     "finishReason": "SAFETY"}]}, None

    with StubServer(responder) as srv:
        pred = _engine(srv.base_url).predict(_req())
    assert not pred.ok
    assert "SAFETY" in pred.error


def test_gemini_http_error_is_captured(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "bad-gemini-key")

    def responder(record):
        return 403, {"error": {"message": "API key not valid"}}, None

    with StubServer(responder) as srv:
        pred = _engine(srv.base_url).predict(_req())
    assert not pred.ok
    assert "HTTP 403" in pred.error
    assert "API key not valid" in pred.error
    assert KEY_ENV in pred.error
    assert "bad-gemini-key" not in pred.error


def test_gemini_missing_api_key(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with StubServer(_ok()) as srv:
        pred = _engine(srv.base_url).predict(_req())
    assert not pred.ok
    assert "缺少 API Key" in pred.error
    assert KEY_ENV in pred.error
    assert srv.records == []


def test_gemini_missing_model():
    eng = build_engine({"id": "gemini", "type": "vlm.gemini",
                        "params": {"api_key_env": KEY_ENV}})
    pred = eng.predict(_req())
    assert not pred.ok
    assert "缺少 params.model" in pred.error


def test_gemini_multiple_text_parts_joined(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")

    def responder(record):
        return 200, {"candidates": [{"content": {"parts": [
            {"text": "第一行"}, {"text": "第二行"},
        ]}, "finishReason": "STOP"}]}, None

    with StubServer(responder) as srv:
        pred = _engine(srv.base_url).predict(_req())
    assert pred.ok, pred.error
    assert pred.text == "第一行第二行"
