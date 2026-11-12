"""引擎基类与注册表。新引擎只需继承 BaseEngine + @register("type.name")。"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Callable

from core.types import EngineOutput, EngineRequest, Prediction


ENGINE_REGISTRY: dict[str, type["BaseEngine"]] = {}


def register(type_name: str) -> Callable[[type], type]:
    def deco(cls):
        cls.type_name = type_name
        if type_name in ENGINE_REGISTRY and ENGINE_REGISTRY[type_name] is not cls:
            raise RuntimeError(f"引擎类型重复注册: {type_name}")
        ENGINE_REGISTRY[type_name] = cls
        return cls
    return deco


def load_builtin_adapters() -> None:
    """导入全部内置 adapter 触发注册。缺依赖的模块静默跳过（不影响其它引擎）。"""
    import importlib
    import pkgutil
    import adapters as _pkg

    for m in pkgutil.iter_modules(_pkg.__path__):
        if m.name.startswith("_") or m.name == "base":
            continue
        try:
            importlib.import_module(f"adapters.{m.name}")
        except Exception as e:  # noqa: BLE001
            # 依赖缺失不该阻断整个评测，只在 --debug 时可见
            if os.environ.get("VEVAL_DEBUG"):
                print(f"[warn] adapter 加载失败 adapters.{m.name}: {e}")


class BaseEngine:
    """统一引擎接口。模态无关：声明 `modalities` 即可同时用于图片/视频/音频。

    子类实现 `_predict()`；计量、异常兜底、成本核算都在 `predict()` 里做。
    """
    type_name: str = ""
    # 声明能力位，runner 据此跳过不匹配的任务组合
    capabilities: tuple[str, ...] = ("recognize",)
    # 声明支持的输入模态，runner 据此跳过不匹配的样本
    modalities: tuple[str, ...] = ("image",)

    def __init__(self, engine_id: str, params: dict[str, Any] | None = None,
                 cost: dict[str, Any] | None = None):
        self.engine_id = engine_id
        self.params = params or {}
        self.cost_cfg = cost or {}
        self._validate()

    # ---- 子类可覆写 ----
    def _validate(self) -> None:
        pass

    def warmup(self) -> None:
        """可选：模型预加载，不计入样本延迟。"""

    def _predict(self, req: EngineRequest) -> EngineOutput:
        raise NotImplementedError

    def build_request(self, req: EngineRequest) -> EngineRequest:
        """子类可在这里注入默认 prompt / schema。"""
        return req

    # ---- 统一入口 ----
    def supports(self, task: str) -> bool:
        return task in self.capabilities

    def accepts(self, modality: str) -> bool:
        return modality in self.modalities

    def predict(self, req: EngineRequest) -> Prediction:
        req = self.build_request(req)
        t0 = time.perf_counter()
        try:
            out = self._predict(req)
            err = None
        except Exception as e:  # noqa: BLE001
            out = EngineOutput()
            err = f"{type(e).__name__}: {e}"
        latency_ms = (time.perf_counter() - t0) * 1000
        usage = out.usage or {}
        return Prediction(
            engine_id=self.engine_id,
            sample_id=req.sample_id,
            task=req.task,
            modality=req.modality,
            text=out.text or "",
            lines=out.lines,
            fields=out.fields,
            latency_ms=latency_ms,
            cost_usd=self.compute_cost(usage),
            usage=usage,
            error=err,
            raw=out.raw,
            meta={**(out.meta or {}), "device": self.device, **self.describe()},
        )

    # ---- 成本核算 ----
    def compute_cost(self, usage: dict[str, Any]) -> float:
        """cost 配置支持（可分项叠加）：
        input_per_1m / output_per_1m  token 计价
        per_image                     按张计价（图片 OCR API 常用）
        per_second / per_minute       按音频、视频时长计价
        per_call                      按请求计价
        内部统一 USD，currency 仅作展示。
        """
        c = self.cost_cfg
        usd = 0.0
        usd += usage.get("input_tokens", 0) / 1e6 * float(c.get("input_per_1m", 0))
        usd += usage.get("output_tokens", 0) / 1e6 * float(c.get("output_per_1m", 0))
        usd += usage.get("images", 1) * float(c.get("per_image", 0))
        usd += usage.get("seconds", 0) * float(c.get("per_second", 0))
        usd += usage.get("seconds", 0) / 60 * float(c.get("per_minute", 0))
        usd += usage.get("calls", 1) * float(c.get("per_call", 0))
        return usd

    # ---- 元信息 ----
    @property
    def device(self) -> str:
        return str(self.params.get("device", "cpu"))

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "capabilities": list(self.capabilities),
            "modalities": list(self.modalities),
        }

    def param_fingerprint(self) -> str:
        """用于 cache key：参数变化即失效。prompt 也进去。"""
        blob = repr(sorted((k, str(v)) for k, v in self.params.items()))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def build_engine(cfg: dict[str, Any]) -> BaseEngine:
    load_builtin_adapters()
    tname = cfg["type"]
    if tname not in ENGINE_REGISTRY:
        raise KeyError(
            f"未注册的引擎类型: {tname}\n已注册: {sorted(ENGINE_REGISTRY)}"
        )
    return ENGINE_REGISTRY[tname](
        engine_id=cfg.get("id") or tname,
        params=cfg.get("params") or {},
        cost=cfg.get("cost") or {},
    )
