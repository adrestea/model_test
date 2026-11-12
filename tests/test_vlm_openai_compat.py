"""vlm.openai_compat：请求构造 / usage / 错误处理（本地假端点，无外网）。"""
from __future__ import annotations

import base64
import json

import pytest

from adapters.base import build_engine
from core.config import DEFAULT_PROMPT
from core.types import EngineRequest
from tests.test_vlm_http_stub import PNG_BYTES, StubServer

KEY_ENV = "VEVAL_TEST_OPENAI_KEY"


def _ok(content="发票号码：12345", usage=None):
    def responder(record):
        return 200, {
            "id": "chatcmpl-stub",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": usage if usage is not None else {
                "prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
            },
        }, None
    return responder


def _engine(base_url, **params):
    params = {"base_url": f"{base_url}/v1", "model": "qwen-vl-max",
              "api_key_env": KEY_ENV, **params}
    return build_engine({
        "id": "qwen-vl-max", "type": "vlm.openai_compat", "params": params,
        "cost": {"input_per_1m": 3.0, "output_per_1m": 9.0},
    })


def _req(**kw):
    kw.setdefault("sample_id", "s1")
    kw.setdefault("task", "recognize")
    kw.setdefault("media_bytes", PNG_BYTES)
    return EngineRequest(**kw)


def test_openai_compat_request_usage_and_cost(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "test-key-123")
    with StubServer(_ok()) as srv:
        pred = _engine(srv.base_url, max_tokens=2048,
                       image_detail="high").predict(_req())

    assert pred.ok, pred.error
    assert pred.text == "发票号码：12345"
    assert pred.usage["input_tokens"] == 120
    assert pred.usage["output_tokens"] == 30
    assert pred.usage["total_tokens"] == 150
    assert pred.usage["images"] == 1
    # 3.0 USD/1M input + 9.0 USD/1M output
    assert pred.cost_usd == (120 / 1e6 * 3.0) + (30 / 1e6 * 9.0)
    assert pred.meta["type"] == "vlm.openai_compat"
    assert pred.meta["device"] == "remote"
    assert pred.meta["model"] == "qwen-vl-max"

    assert len(srv.records) == 1
    rec = srv.records[0]
    assert rec["path"] == "/v1/chat/completions"
    assert rec["headers"]["authorization"] == "Bearer test-key-123"
    body = rec["body"]
    assert body["model"] == "qwen-vl-max"
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.0
    assert body["stream"] is False
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": DEFAULT_PROMPT}
    image = parts[1]["image_url"]
    assert image["detail"] == "high"
    prefix = "data:image/png;base64,"
    assert image["url"].startswith(prefix)
    assert base64.b64decode(image["url"][len(prefix):]) == PNG_BYTES


def test_openai_compat_prompt_file_and_runtime_override(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY_ENV, "test-key-123")
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("从文件读取的 prompt", encoding="utf-8")
    with StubServer(_ok()) as srv:
        eng = _engine(srv.base_url, prompt_file=str(prompt_file))
        pred1 = eng.predict(_req())
        assert pred1.ok, pred1.error
        assert srv.records[-1]["body"]["messages"][0]["content"][0]["text"] == \
            "从文件读取的 prompt"

        pred2 = eng.predict(_req(prompt="运行时覆盖 prompt"))
        assert pred2.ok, pred2.error
        assert srv.records[-1]["body"]["messages"][0]["content"][0]["text"] == \
            "运行时覆盖 prompt"


def test_openai_compat_params_prompt_wins_over_file(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY_ENV, "k")
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("文件", encoding="utf-8")
    with StubServer(_ok()) as srv:
        eng = _engine(srv.base_url, prompt="参数 prompt", prompt_file=str(prompt_file))
        assert eng.predict(_req()).ok
        assert srv.records[-1]["body"]["messages"][0]["content"][0]["text"] == "参数 prompt"


def test_openai_compat_content_parts_joined(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")
    content = [{"type": "text", "text": "甲"}, {"type": "text", "text": "乙"}]
    with StubServer(_ok(content=content)) as srv:
        pred = _engine(srv.base_url).predict(_req())
    assert pred.ok, pred.error
    assert pred.text == "甲\n乙"


def test_openai_compat_http_error_is_captured(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "bad-key")

    def responder(record):
        return 401, {"error": {"message": "Incorrect API key provided"}}, None

    with StubServer(responder) as srv:
        pred = _engine(srv.base_url).predict(_req())

    assert not pred.ok
    assert "HTTP 401" in pred.error
    assert "Incorrect API key" in pred.error
    assert KEY_ENV in pred.error          # 提示要检查哪个环境变量
    assert "bad-key" not in pred.error     # 不能回显密钥
    assert pred.text == ""


def test_openai_compat_missing_api_key_fails_before_request(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    with StubServer(_ok()) as srv:
        pred = _engine(srv.base_url).predict(_req())
    assert not pred.ok
    assert "缺少 API Key" in pred.error
    assert KEY_ENV in pred.error
    assert srv.records == []               # 没有发请求


def test_openai_compat_missing_image(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")
    with StubServer(_ok()) as srv:
        pred = _engine(srv.base_url).predict(
            EngineRequest(sample_id="s1", task="recognize")
        )
    assert not pred.ok
    assert "未提供图片" in pred.error
    assert srv.records == []


def test_openai_compat_missing_image_file(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY_ENV, "k")
    with StubServer(_ok()) as srv:
        pred = _engine(srv.base_url).predict(
            _req(media_bytes=None, media_path=str(tmp_path / "nope.png"))
        )
    assert not pred.ok
    assert "图片文件不存在" in pred.error
    assert srv.records == []


def test_openai_compat_reads_media_path_and_sniffs_jpeg(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY_ENV, "k")
    jpeg = b"\xff\xd8\xff\xe0" + b"fake-jpeg" * 3
    path = tmp_path / "a.jpg"
    path.write_bytes(jpeg)
    with StubServer(_ok()) as srv:
        pred = _engine(srv.base_url).predict(
            _req(media_bytes=None, media_path=str(path))
        )
    assert pred.ok, pred.error
    assert pred.meta["image_mime"] == "image/jpeg"
    assert pred.meta["image_bytes"] == len(jpeg)
    url = srv.records[0]["body"]["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")


def test_openai_compat_truncated_output_reports_length(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")

    def responder(record):
        return 200, {
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }, None

    with StubServer(responder) as srv:
        pred = _engine(srv.base_url).predict(_req())
    assert not pred.ok
    assert "截断" in pred.error
    assert "max_tokens" in pred.error


def test_openai_compat_extract_fields_from_json(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")
    content = '```json\n{"invoice_no": "12345", "total": 99.5}\n```'
    schema = {"type": "object", "properties": {"invoice_no": {"type": "string"}}}
    with StubServer(_ok(content=content)) as srv:
        pred = _engine(srv.base_url).predict(
            _req(task="extract", schema=schema)
        )
    assert pred.ok, pred.error
    assert pred.fields == {"invoice_no": "12345", "total": 99.5}
    prompt = srv.records[0]["body"]["messages"][0]["content"][0]["text"]
    assert "JSON Schema" in prompt
    assert json.dumps(schema, ensure_ascii=False, sort_keys=True) in prompt


def test_openai_compat_base_url_may_be_full_endpoint(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")
    with StubServer(_ok()) as srv:
        eng = build_engine({
            "id": "custom", "type": "vlm.openai_compat",
            "params": {"base_url": f"{srv.base_url}/v1/chat/completions",
                       "model": "m", "api_key_env": KEY_ENV},
        })
        pred = eng.predict(_req())
    assert pred.ok, pred.error
    assert srv.records[0]["path"] == "/v1/chat/completions"


def test_http_layer_uses_requests_when_available():
    pytest.importorskip("requests")
    from adapters._http import _session
    assert _session() is not None
