"""注册表与 configs/full.yaml 的一致性：VLM 引擎必须能被零配置构造。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from adapters.base import ENGINE_REGISTRY, build_engine, load_builtin_adapters

ROOT = Path(__file__).resolve().parents[1]
VLM_TYPES = {"vlm.openai_compat", "vlm.gemini", "vlm.local"}


def _vlm_engines():
    cfg = yaml.safe_load((ROOT / "configs" / "full.yaml").read_text(encoding="utf-8"))
    return [e for e in cfg["engines"] if str(e.get("type", "")).startswith("vlm.")]


def test_builtin_vlm_types_registered():
    load_builtin_adapters()
    assert VLM_TYPES <= set(ENGINE_REGISTRY)
    for type_name in VLM_TYPES:
        cls = ENGINE_REGISTRY[type_name]
        assert cls.modalities == ("image",)
        assert "recognize" in cls.capabilities


def test_every_vlm_engine_in_full_yaml_builds_without_keys(monkeypatch):
    # 本机没有任何在线 key：构造阶段不允许因缺 key 抛异常（否则整个矩阵 run 起不来）
    for env in ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY",
                "GEMINI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    engines = _vlm_engines()
    assert engines, "configs/full.yaml 里应有 VLM 引擎"
    for cfg in engines:
        eng = build_engine(cfg)
        assert eng.type_name == cfg["type"]
        assert eng.engine_id == cfg["id"]
        assert eng.accepts("image")
        assert eng.supports("recognize")
        assert eng.describe()["type"] == cfg["type"]
        assert isinstance(eng.param_fingerprint(), str)


def test_full_yaml_local_backend_and_device_values_are_supported():
    local = [e for e in _vlm_engines() if e["type"] == "vlm.local"]
    assert local, "configs/full.yaml 应包含 vlm.local"
    for cfg in local:
        params = cfg.get("params") or {}
        assert params.get("backend") in ("ollama", "openai_compat", "transformers")
        assert params.get("device", "auto") in ("auto", "cpu", "cuda", "mps") or \
            str(params.get("device", "")).startswith("cuda:")
        eng = build_engine(cfg)
        assert eng.device in ("cpu", "cuda", "mps") or eng.device.startswith("cuda:")


def test_unknown_engine_type_raises_keyerror():
    with pytest.raises(KeyError):
        build_engine({"id": "nope", "type": "vlm.not_exists", "params": {}})


def test_online_engines_do_not_require_key_at_construction():
    for cfg in _vlm_engines():
        if cfg["type"] == "vlm.local":
            continue
        eng = build_engine(cfg)
        assert eng.device == "remote"
