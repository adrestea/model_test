"""测试用本地假 HTTP 端点。

不访问任何外部网络：在 127.0.0.1 随机端口起 ``ThreadingHTTPServer``，
记录请求并返回预设响应。文件名保持 ``test_vlm_*`` 前缀，本身不含用例，
由其它测试模块 import 复用。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"veval-test-image" * 4

Responder = Callable[[dict[str, Any]], tuple[int, Any, dict[str, str] | None]]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw) if raw else None
        except (ValueError, UnicodeDecodeError):
            body = None
        record = {
            "method": "POST",
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": body,
            "raw": raw,
        }
        self.server.records.append(record)  # type: ignore[attr-defined]
        status, payload, extra = self.server.responder(record)  # type: ignore[attr-defined]
        data = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False
        ).encode("utf-8")
        extra = extra or {}
        self.send_response(status)
        self.send_header("Content-Type", extra.get("Content-Type", "application/json"))
        for key, value in extra.items():
            if key.lower() != "content-type":
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: Any) -> None:  # 静音
        return


class StubServer:
    """上下文管理器：``with StubServer(responder) as srv: srv.base_url``。"""

    def __init__(self, responder: Responder):
        self._responder = responder
        self.records: list[dict[str, Any]] = []
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "StubServer":
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.responder = self._responder  # type: ignore[attr-defined]
        self._httpd.records = self.records  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02},
            daemon=True,
        )
        self._thread.start()
        return self

    @property
    def base_url(self) -> str:
        assert self._httpd is not None
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __exit__(self, *exc: Any) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
