"""预测缓存。

cache key = sha256(媒体字节 + engine_id + 参数指纹 + task + prompt + 归一化配置)
参数、prompt、归一化口径任一变化都会失效，不会拿旧结果冒充新结果。

命中缓存时不重复计延迟与成本（meta 里保留原始值），
这样重复跑同一配置不会被缓存"刷"出更漂亮的效率数据。
媒体字节相同的样本复用同一份输出，但 sample_id 会改写为当前样本。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters._vlm_util import resolve_prompt
from adapters.base import BaseEngine
from core.text import NormalizeConfig
from core.types import EngineRequest, Prediction

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(".cache/predictions")


def _prompt_identity(req: EngineRequest, params: dict[str, Any]) -> str:
    """缓存键里的 prompt 分量。

    只哈希 ``req.prompt`` 会漏掉 VLM 通过 ``params.prompt_file`` 读文件的场景：
    文件路径不变、内容改了，缓存却仍命中。这里复用 adapter 的 resolve_prompt
    优先级（req.prompt > params.prompt > params.prompt_file 内容 > 默认 prompt），
    保证缓存键与真实推理实际使用的 prompt 完全一致。
    """
    try:
        return resolve_prompt(req, params)
    except Exception:  # noqa: BLE001 - prompt_file 缺失等错误留给 predict 阶段报
        # 回退为按各来源原文摘要，保证 key 稳定可复现
        parts = [
            req.prompt or "",
            str(params.get("prompt") or ""),
            str(params.get("prompt_file") or params.get("prompt_path") or ""),
        ]
        return "\x00".join(parts)


def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """流式计算文件摘要，避免把大视频整段读进内存。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


@dataclass
class PredictionCache:
    root: Path = DEFAULT_CACHE_DIR
    enabled: bool = True

    def key(
        self,
        engine: BaseEngine,
        req: EngineRequest,
        media_digest: str,
        normalize: NormalizeConfig,
    ) -> str:
        prompt_hash = hashlib.sha256(
            _prompt_identity(req, engine.params).encode()
        ).hexdigest()[:16]
        payload: dict[str, Any] = {
            "media": media_digest,
            "engine_id": engine.engine_id,
            "engine_type": engine.type_name,
            "params": engine.param_fingerprint(),
            "task": req.task,
            "prompt": prompt_hash,
            "normalize": normalize.to_dict(),
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key[2:]}.json"

    def get(self, key: str, sample_id: str | None = None) -> Prediction | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            pred = Prediction.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - 缓存损坏按未命中处理，不阻断评测
            log.warning("缓存文件损坏，已忽略: %s", path, exc_info=True)
            return None
        pred.meta = {
            **(pred.meta or {}),
            "cache_hit": True,
            "cached_latency_ms": pred.latency_ms,
            "cached_cost_usd": pred.cost_usd,
        }
        # 媒体字节相同的样本复用同一份输出，但样本身份必须跟着当前请求走
        if sample_id is not None:
            pred.sample_id = sample_id
        pred.latency_ms = 0.0
        pred.cost_usd = 0.0
        return pred

    def put(self, key: str, pred: Prediction) -> None:
        """原子替换 + 唯一临时名，并发写同一 key 也安全。"""
        if not self.enabled:
            return
        path = self._path(key)
        tmp = path.with_suffix(f".tmp.{uuid.uuid4().hex}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(pred.to_dict(), ensure_ascii=False), encoding="utf-8"
            )
            os.replace(tmp, path)
        except OSError:  # 缓存写失败只告警，不影响本次评测结果
            log.warning("缓存写入失败: %s", path, exc_info=True)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
