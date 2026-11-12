"""HTTP 请求与 API Key 解析的私有辅助（不注册引擎）。

约定：
- 只有这里 import requests / urllib，adapter 逻辑保持纯粹；
- 所有网络异常都翻译成带排查建议的中文异常，交给 ``BaseEngine.predict``
  统一兜底为 ``Prediction.error``，因此单个引擎缺 key / 断网不会中断整个 run；
- 异常文本里的 URL query 密钥会做脱敏。
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Mapping

DEFAULT_TIMEOUT_S = 120.0
_BODY_LIMIT = 800

_KEY_RE = re.compile(r"([?&](?:key|api_key|api-key|access_token|token)=)[^&\s\"']+", re.I)


class AdapterHTTPError(RuntimeError):
    """带 HTTP 状态码与响应片段的适配层异常。"""

    def __init__(self, message: str, *, status: int | None = None,
                 body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


_tls = threading.local()


def _session():
    """线程内复用 requests.Session（连接池）；requests 缺失时返回 None 走 urllib。"""
    try:
        import requests  # noqa: F401
    except ImportError:
        return None
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "veval-vlm-adapter/0.1"})
        _tls.session = s
    return s


def env_value(name: str | None) -> str | None:
    if not name:
        return None
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None


def key_env_name(params: Mapping[str, Any], default_env: str) -> str:
    return str(params.get("api_key_env") or default_env or "").strip()


def resolve_api_key(params: Mapping[str, Any], default_env: str, *,
                    required: bool, engine_label: str) -> str | None:
    """按 ``api_key_env`` -> ``api_key`` 的顺序取密钥。

    在线引擎 ``required=True``：缺失时抛中文异常，明确告知要设置哪个环境变量。
    本地引擎 ``required=False``：本地服务通常不校验 key，缺失时直接返回 None。
    """
    name = key_env_name(params, default_env)
    key = env_value(name)
    if not key:
        direct = params.get("api_key")
        if isinstance(direct, str) and direct.strip():
            key = direct.strip()
    if key:
        return key
    if not required:
        return None
    raise AdapterHTTPError(
        f"{engine_label}: 缺少 API Key，未设置环境变量 {name or '(api_key_env)'}。"
        f"请先执行 `export {name or 'XXX_API_KEY'}=<your-key>`，"
        "或把 params.api_key_env 指向已存在的环境变量名。"
        "（adapter 不会读取硬编码密钥，也不会打印密钥内容）"
    )


def redact(text: str) -> str:
    """把 URL 里可能出现的 key/token 参数替换为 ***。"""
    return _KEY_RE.sub(r"\1***", text)


def _excerpt(body: str | None, limit: int = _BODY_LIMIT) -> str:
    if not body:
        return ""
    flat = redact(str(body).strip().replace("\n", " ").replace("\r", " "))
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _json_error_message(body: str | None) -> str:
    """从常见错误结构里抽出 message，抽不到就返回空串。"""
    if not body:
        return ""
    try:
        obj = json.loads(body)
    except (ValueError, TypeError):
        return ""
    if not isinstance(obj, dict):
        return ""
    err = obj.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("msg")
        if msg:
            return str(msg)
    if isinstance(err, str):
        return err
    if obj.get("message"):
        return str(obj["message"])
    errors = obj.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("message") or "")
    return ""


def _status_hint(status: int, engine_label: str, api_key_env: str | None) -> str:
    if status in (401, 403):
        env_hint = f"环境变量 {api_key_env}" if api_key_env else "API Key"
        return f"鉴权失败：请检查{env_hint}是否有效、是否有该模型权限。"
    if status == 400:
        return "请求格式被拒绝：请检查 model / base_url / 图片编码方式是否被该服务支持。"
    if status == 404:
        return ("接口或模型不存在：请检查 base_url 路径与 model 名称；"
                "本地服务请确认模型已 pull（如 `ollama pull <model>`）。")
    if status == 413:
        return "请求体过大：请压缩图片或降低分辨率后重试。"
    if status == 429:
        return "触发限流或额度不足：请降低 concurrency，或稍后重试。"
    if 500 <= status < 600:
        return "服务端错误：可稍后重试；若持续出现请检查服务日志。"
    return ""


def _transport_error(exc: Exception, url: str, timeout: float,
                     engine_label: str) -> AdapterHTTPError:
    name = type(exc).__name__
    lower_name = name.lower()
    msg = str(exc)
    lower_msg = msg.lower()
    target = redact(url)
    if "timeout" in lower_name or "timed out" in lower_msg:
        return AdapterHTTPError(
            f"{engine_label}: 请求超时（timeout_s={timeout:g}s）: {target}。"
            "可调大 params.timeout_s；本地大模型在 CPU 上建议 300s 以上。"
        )
    if ("connection" in lower_name or "urlerror" in lower_name
            or "ssl" in lower_name or "refused" in lower_msg):
        return AdapterHTTPError(
            f"{engine_label}: 无法连接 {target}（{name}: {msg}）。"
            "请检查 base_url / 网络；本地 ollama 需先 `ollama serve`，"
            "本地 OpenAI 兼容服务需确认端口已启动。"
        )
    return AdapterHTTPError(f"{engine_label}: 网络请求失败（{name}: {msg}）: {target}")


def post_json(url: str, payload: Mapping[str, Any],
              headers: Mapping[str, str] | None = None, *,
              timeout: float = DEFAULT_TIMEOUT_S,
              engine_label: str = "HTTP",
              api_key_env: str | None = None) -> dict[str, Any]:
    """POST JSON 并返回 dict；非 2xx / 非 JSON / 网络错误均抛 AdapterHTTPError。"""
    try:
        timeout = float(timeout or DEFAULT_TIMEOUT_S)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_S
    hdrs = {str(k): str(v) for k, v in (headers or {}).items()}
    session = _session()
    if session is not None:
        return _post_requests(session, url, payload, hdrs, timeout,
                              engine_label, api_key_env)
    return _post_urllib(url, payload, hdrs, timeout, engine_label, api_key_env)


def _post_requests(session, url: str, payload: Mapping[str, Any],
                   headers: dict[str, str], timeout: float,
                   engine_label: str, api_key_env: str | None) -> dict[str, Any]:
    import requests

    try:
        resp = session.post(url, json=dict(payload), headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:  # 含 Timeout / ConnectionError
        raise _transport_error(e, url, timeout, engine_label) from e

    body_text = resp.text or ""
    if resp.status_code >= 400:
        detail = _json_error_message(body_text)
        parts = [f"{engine_label} 请求失败: HTTP {resp.status_code}"]
        reason = (resp.reason or "").strip()
        if reason:
            parts[0] += f" {reason}"
        hint = _status_hint(resp.status_code, engine_label, api_key_env)
        if hint:
            parts.append(hint)
        if detail:
            parts.append(f"服务端消息: {redact(detail)[:500]}")
        snippet = _excerpt(body_text)
        if snippet and not detail:
            parts.append(f"响应片段: {snippet}")
        raise AdapterHTTPError("；".join(parts), status=resp.status_code,
                               body=snippet)

    try:
        data = resp.json()
    except ValueError as e:
        snippet = _excerpt(body_text)
        raise AdapterHTTPError(
            f"{engine_label}: 返回的不是合法 JSON（HTTP {resp.status_code}）。"
            f"响应片段: {snippet or '(空响应)'}",
            status=resp.status_code, body=snippet,
        ) from e
    if not isinstance(data, dict):
        raise AdapterHTTPError(
            f"{engine_label}: 期望 JSON 对象，实际得到 {type(data).__name__}",
            status=resp.status_code,
        )
    return data


def _post_urllib(url: str, payload: Mapping[str, Any], headers: dict[str, str],
                 timeout: float, engine_label: str,
                 api_key_env: str | None) -> dict[str, Any]:
    """requests 缺失时的标准库兜底，保证无三方依赖也能跑通 mock 端点。"""
    import socket
    import urllib.error
    import urllib.request

    body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "application/json", **headers}
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        detail = _json_error_message(raw)
        parts = [f"{engine_label} 请求失败: HTTP {e.code}"]
        hint = _status_hint(e.code, engine_label, api_key_env)
        if hint:
            parts.append(hint)
        if detail:
            parts.append(f"服务端消息: {redact(detail)[:500]}")
        else:
            snippet = _excerpt(raw)
            if snippet:
                parts.append(f"响应片段: {snippet}")
        raise AdapterHTTPError("；".join(parts), status=e.code,
                               body=_excerpt(raw)) from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise _transport_error(e, url, timeout, engine_label) from e

    try:
        data = json.loads(raw)
    except ValueError as e:
        snippet = _excerpt(raw)
        raise AdapterHTTPError(
            f"{engine_label}: 返回的不是合法 JSON。响应片段: {snippet or '(空响应)'}",
            body=snippet,
        ) from e
    if not isinstance(data, dict):
        raise AdapterHTTPError(
            f"{engine_label}: 期望 JSON 对象，实际得到 {type(data).__name__}"
        )
    return data
