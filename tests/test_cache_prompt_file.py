"""prompt_file 缓存失效回归：改 prompt 文件内容（路径不变）必须让缓存失效。

背景：PredictionCache.key 以前只哈希 req.prompt 与 params（值指纹），
VLM 通过 params.prompt_file 读文件时，改文件内容但路径不变 -> 缓存仍命中的漏洞。
"""
from __future__ import annotations

import pytest

import tests.fake_engines  # noqa: F401 - 触发 test.echo 注册
from core.text import NormalizeConfig
from core.types import EngineRequest
from runner.cache import PredictionCache
from tests.fake_engines import EchoEngine


def _key(cache: PredictionCache, engine: EchoEngine, req: EngineRequest) -> str:
    return cache.key(engine, req, "same-media-digest", NormalizeConfig())


def test_prompt_file_content_invalidates_cache(tmp_path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("第一版提示词", encoding="utf-8")

    cache = PredictionCache(root=tmp_path / "c")
    engine = EchoEngine("v", {"prompt_file": str(prompt_file)})
    req = EngineRequest(sample_id="s1", task="recognize")

    k1 = _key(cache, engine, req)

    # 文件内容变化（路径不变）
    prompt_file.write_text("第二版提示词，改了内容", encoding="utf-8")
    k2 = _key(cache, engine, req)

    assert k1 != k2


def test_prompt_file_priority_matches_adapter(tmp_path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("来自文件", encoding="utf-8")

    cache = PredictionCache(root=tmp_path / "c")
    engine = EchoEngine("v", {"prompt": "来自参数", "prompt_file": str(prompt_file)})
    base_req = EngineRequest(sample_id="s1", task="recognize")

    # req.prompt 优先级最高
    k_req = _key(cache, engine, EngineRequest(
        sample_id="s1", task="recognize", prompt="来自请求",
    ))
    # 无 req.prompt 时 params.prompt 优先于 prompt_file
    k_param = _key(cache, engine, base_req)

    engine_file_only = EchoEngine("v", {"prompt_file": str(prompt_file)})
    k_file = _key(cache, engine_file_only, base_req)

    assert len({k_req, k_param, k_file}) == 3


def test_missing_prompt_file_keeps_key_stable(tmp_path) -> None:
    """prompt_file 不存在时 key 仍可计算（真实错误由 predict 阶段报出），
    且同一参数下 key 稳定可复现。"""
    cache = PredictionCache(root=tmp_path / "c")
    engine = EchoEngine("v", {"prompt_file": str(tmp_path / "nope.txt")})
    req = EngineRequest(sample_id="s1", task="recognize")

    assert _key(cache, engine, req) == _key(cache, engine, req)


def test_full_cache_roundtrip_invalidated_by_prompt_file(tmp_path) -> None:
    """端到端：改 prompt 文件内容后第二次 run 必须重新调用引擎，而不是命中缓存。"""
    from core.config import load_config
    from runner.run import Runner
    from tests.helpers import write_config, write_dataset

    ds = write_dataset(tmp_path, {"s1": "你好"})
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("v1", encoding="utf-8")

    def run_with_prompt() -> int:
        cfg_path = write_config(
            tmp_path, ds,
            engines=[{
                "id": "echo",
                "type": "test.echo",
                "params": {"outputs": {"s1": "你好"}, "prompt_file": str(prompt_file)},
            }],
            cache=True,
        )
        engine = EchoEngine("echo", {
            "outputs": {"s1": "你好"}, "prompt_file": str(prompt_file),
        })
        runner = Runner(load_config(cfg_path), engines=[engine])
        runner.run()
        return engine.calls

    first_calls = run_with_prompt()
    # 改文件内容，路径不变
    prompt_file.write_text("v2 - 改了", encoding="utf-8")
    second_calls = run_with_prompt()

    # 每次 run 都是全新引擎实例；缓存未失效时第二次应为 0 次调用，
    # 修复后因 key 变化必须重新推理，应为 1 次。
    assert first_calls == 1
    assert second_calls == 1