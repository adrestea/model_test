"""云 OCR 适配（阿里云 / 腾讯云 / 百度智能云），单类多 provider。

type: ocr.cloud
params.provider 选 aliyun | tencent | baidu。

    - id: aliyun-ocr
      type: ocr.cloud
      params: { provider: aliyun }        # 读 ALIYUN_OCR_APPCODE
      cost: { per_image: 0.0042 }

环境变量（只依赖标准库，无额外 pip 包）：
    aliyun   ALIYUN_OCR_APPCODE                      阿里云市场「OCR 文字识别」AppCode
    tencent  TENCENT_SECRET_ID / TENCENT_SECRET_KEY  CAM 密钥（需 OCR 读权限）
    baidu    BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY  百度智能云 OCR 应用 AK/SK

也可在 params 里用 *_env 键改读别的变量名，例如：
    params: { provider: tencent, secret_id_env: MY_TC_ID, secret_key_env: MY_TC_KEY }

实现说明：直接用 urllib 调各家 REST API，不引入 SDK（SDK 体积大、版本冲突多）。
三家都返回"每个检测框一行文本"，正好映射成 Line.text + Line.box（像素坐标）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from adapters._ocr_common import (
    image_file,
    image_size,
    lines_to_text,
    poly_to_box,
    read_b64,
    rect_to_box,
    require_env,
)
from adapters.base import BaseEngine, register
from core.types import EngineOutput, EngineRequest, Line

PROVIDERS = ("aliyun", "tencent", "baidu")

# 环境变量名清单（报告/文档里直接引用）
ENV_VARS = {
    "aliyun": ["ALIYUN_OCR_APPCODE"],
    "tencent": ["TENCENT_SECRET_ID", "TENCENT_SECRET_KEY"],
    "baidu": ["BAIDU_OCR_API_KEY", "BAIDU_OCR_SECRET_KEY"],
}


@register("ocr.cloud")
class CloudOCREngine(BaseEngine):
    type_name = "ocr.cloud"
    capabilities = ("recognize", "lines", "boxes")
    modalities = ("image",)

    def _validate(self) -> None:
        provider = str(self.params.get("provider") or "").strip().lower()
        if not provider:
            raise ValueError(
                "ocr.cloud 必须在 params 里指定 provider，可选：aliyun | tencent | baidu\n"
                "例：params: { provider: aliyun }"
            )
        if provider not in PROVIDERS:
            raise ValueError(
                f"不支持的云 OCR provider: {provider}（可选：{' | '.join(PROVIDERS)}）"
            )
        self.provider = provider

    def _predict(self, req: EngineRequest) -> EngineOutput:
        fn = _PROVIDER_FNS[self.provider]
        with image_file(req) as path:
            size = image_size(path)
            b64 = read_b64(path)
            t0 = time.perf_counter()
            lines, raw, meta = fn(self.params, b64)
            api_ms = (time.perf_counter() - t0) * 1000

        lines.sort(key=_reading_order)
        return EngineOutput(
            text=lines_to_text(lines),
            lines=lines,
            usage={"images": 1},
            raw=raw,
            meta={
                "engine": "cloud_ocr",
                "provider": self.provider,
                "image_size": list(size) if size else None,
                "api_ms": round(api_ms, 2),
                **meta,
            },
        )


def _reading_order(line: Line) -> tuple[float, float]:
    if line.box is None:
        return (float("inf"), float("inf"))
    return ((line.box.y1 + line.box.y2) / 2, line.box.x1)


# --------------------------------------------------------------------------
# HTTP 基础
# --------------------------------------------------------------------------
def _http(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"HTTP {e.code} 调用失败: {url}\n{detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误，无法访问 {url}: {e.reason}") from e


def _json_body(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _decoded(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"响应不是合法 JSON（前 300 字）：{raw[:300]!r}") from e


def _to_float(v: Any, scale: float = 1.0) -> float | None:
    try:
        return float(v) * scale
    except (TypeError, ValueError):
        return None


def _pct_score(v: Any) -> float | None:
    """各家置信度有 0~1 也有 0~100，统一成 0~1。"""
    f = _to_float(v)
    if f is None:
        return None
    return round(f / 100.0, 4) if f > 1.0 else round(f, 4)


# --------------------------------------------------------------------------
# 阿里云（市场版 OCR，AppCode 鉴权）
# --------------------------------------------------------------------------
def _aliyun(params: dict[str, Any], b64: str) -> tuple[list[Line], Any, dict[str, Any]]:
    appcode = require_env(
        str(params.get("appcode_env") or "ALIYUN_OCR_APPCODE"),
        why="阿里云市场 OCR 接口用 AppCode 鉴权",
    )
    url = str(
        params.get("endpoint")
        or "https://gjbsb.market.alicloudapi.com/ocrservice/advanced"
    )
    timeout = float(params.get("timeout_s") or 30)
    body = _json_body({"img": b64, "prob": True})

    status, raw = _http(
        url, body,
        {
            "Authorization": f"APPCODE {appcode}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        timeout,
    )
    if status != 200:
        raise RuntimeError(f"阿里云 OCR 返回 HTTP {status}: {raw[:300]!r}")
    data = _decoded(raw)

    words = (
        data.get("prism_wordsInfo")
        or data.get("words_info")
        or data.get("words_result")
        or []
    )
    lines: list[Line] = []
    for w in words:
        text = str(w.get("word") or w.get("words") or w.get("text") or "").strip()
        if not text:
            continue
        box = poly_to_box(w.get("pos"))
        if box is None:
            box = poly_to_box(
                [
                    (w.get("x"), w.get("y")),
                    (
                        (w.get("x") or 0) + (w.get("width") or 0),
                        (w.get("y") or 0) + (w.get("height") or 0),
                    ),
                ]
            )
        if box is None:
            box = rect_to_box(w.get("x"), w.get("y"), w.get("width"), w.get("height"))
        score = _pct_score(w.get("prob", w.get("probability")))
        lines.append(Line(text=text, box=box, score=score))

    if not lines:
        content = (data.get("Data") or {}).get("Content") if isinstance(data.get("Data"), dict) else None
        if content:
            lines = [Line(text=str(content))]
        else:
            raise RuntimeError(
                "阿里云 OCR 响应里没有可解析的文字（检查 endpoint 与开通的接口是否匹配）。"
                f"响应前 300 字：{json.dumps(data, ensure_ascii=False)[:300]}"
            )
    return lines, data, {"endpoint": url}


# --------------------------------------------------------------------------
# 腾讯云（TC3-HMAC-SHA256 签名，GeneralBasicOCR / GeneralAccurateOCR）
# --------------------------------------------------------------------------
def _tencent(params: dict[str, Any], b64: str) -> tuple[list[Line], Any, dict[str, Any]]:
    secret_id = require_env(
        str(params.get("secret_id_env") or "TENCENT_SECRET_ID"),
        why="腾讯云 API 需要 CAM 密钥对",
    )
    secret_key = require_env(
        str(params.get("secret_key_env") or "TENCENT_SECRET_KEY"),
        why="腾讯云 API 需要 CAM 密钥对",
    )
    host = "ocr.tencentcloudapi.com"
    service = "ocr"
    action = str(params.get("action") or "GeneralBasicOCR")
    version = "2018-11-19"
    region = str(params.get("region") or "ap-guangzhou")
    timeout = float(params.get("timeout_s") or 30)

    payload = _json_body({"ImageBase64": b64})
    ts = int(time.time())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

    # 1) canonical request
    canonical_headers = "content-type:application/json; charset=utf-8\nhost:" + host + "\n"
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload).hexdigest()
    canonical_request = "\n".join(
        ["POST", "/", "", canonical_headers, signed_headers, hashed_payload]
    )

    # 2) string to sign
    scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(ts),
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )

    # 3) signature
    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    secret_date = _sign(("TC3" + secret_key).encode(), date)
    secret_service = _sign(secret_date, service)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    authorization = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    status, raw = _http(
        f"https://{host}",
        payload,
        {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": host,
            f"X-TC-Action": action,
            "X-TC-Version": version,
            "X-TC-Timestamp": str(ts),
            "X-TC-Region": region,
        },
        timeout,
    )
    data = _decoded(raw)
    resp = data.get("Response") or {}
    if resp.get("Error"):
        err = resp["Error"]
        raise RuntimeError(
            f"腾讯云 OCR 报错 [{err.get('Code')}]: {err.get('Message')}"
        )

    lines: list[Line] = []
    for d in resp.get("TextDetections") or []:
        text = str(d.get("DetectedText") or "").strip()
        if not text:
            continue
        lines.append(
            Line(
                text=text,
                box=poly_to_box(d.get("Polygon")),
                score=_pct_score(d.get("Confidence")),
            )
        )
    if not lines:
        raise RuntimeError(
            f"腾讯云 OCR 未返回文字（action={action}）。响应：{json.dumps(data, ensure_ascii=False)[:300]}"
        )
    return lines, data, {"endpoint": f"https://{host}", "action": action, "region": region}


# --------------------------------------------------------------------------
# 百度智能云（OAuth token + accurate_basic）
# --------------------------------------------------------------------------
_BAIDU_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}


def _baidu_token(api_key: str, secret_key: str, timeout: float) -> str:
    cached = _BAIDU_TOKEN_CACHE.get((api_key, secret_key))
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    qs = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key,
        }
    )
    status, raw = _http(
        "https://aip.baidubce.com/oauth/2.0/token?" + qs,
        b"",
        {"Content-Type": "application/x-www-form-urlencoded"},
        timeout,
    )
    data = _decoded(raw)
    token = data.get("access_token")
    if not token:
        raise RuntimeError(
            f"百度 OCR 获取 access_token 失败：{data.get('error')} {data.get('error_description')}"
        )
    _BAIDU_TOKEN_CACHE[(api_key, secret_key)] = (
        token, time.time() + float(data.get("expires_in", 2592000))
    )
    return token


def _baidu(params: dict[str, Any], b64: str) -> tuple[list[Line], Any, dict[str, Any]]:
    api_key = require_env(
        str(params.get("api_key_env") or "BAIDU_OCR_API_KEY"),
        why="百度智能云 OCR 应用 AK",
    )
    secret_key = require_env(
        str(params.get("secret_key_env") or "BAIDU_OCR_SECRET_KEY"),
        why="百度智能云 OCR 应用 SK",
    )
    timeout = float(params.get("timeout_s") or 30)
    mode = str(params.get("mode") or "accurate_basic")   # 或 general_basic
    if mode not in ("accurate_basic", "general_basic"):
        raise ValueError(f"不支持的百度 OCR mode: {mode}（可选 accurate_basic | general_basic）")

    token = _baidu_token(api_key, secret_key, timeout)
    url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/{mode}?access_token={token}"
    body = urllib.parse.urlencode({"image": b64}).encode()
    _, raw = _http(
        url, body, {"Content-Type": "application/x-www-form-urlencoded"}, timeout
    )
    data = _decoded(raw)
    if data.get("error_code"):
        raise RuntimeError(
            f"百度 OCR 报错 [{data.get('error_code')}]: {data.get('error_msg')}"
        )

    lines: list[Line] = []
    for w in data.get("words_result") or []:
        text = str(w.get("words") or "").strip()
        if not text:
            continue
        loc = w.get("location") or {}
        box = rect_to_box(loc.get("left"), loc.get("top"), loc.get("width"), loc.get("height"))
        lines.append(Line(text=text, box=box, score=_pct_score(w.get("probability"))))
    if not lines:
        raise RuntimeError(
            f"百度 OCR 未返回文字（mode={mode}）。响应前 300 字："
            f"{json.dumps(data, ensure_ascii=False)[:300]}"
        )
    return lines, data, {"endpoint": f"https://aip.baidubce.com/rest/2.0/ocr/v1/{mode}", "mode": mode}


_PROVIDER_FNS: dict[str, Callable[[dict[str, Any], str], tuple[list[Line], Any, dict[str, Any]]]] = {
    "aliyun": _aliyun,
    "tencent": _tencent,
    "baidu": _baidu,
}


def env_vars_for(provider: str) -> list[str]:
    """给文档/自检脚本用：某个 provider 需要哪些环境变量。"""
    return list(ENV_VARS.get(provider, []))
