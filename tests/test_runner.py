"""runner 执行层测试：矩阵、跳过、重试、超时、重复、缓存、落盘。"""
from __future__ import annotations

import json

import pytest

import tests.fake_engines  # noqa: F401 - 触发 test.echo / test.video_only 注册
from core.config import load_config
from core.text import NormalizeConfig
from core.types import EngineRequest
from runner.cache import PredictionCache
from runner.run import Runner, Job, load_run, save_run
from tests.fake_engines import EchoEngine, VideoOnlyEngine
from tests.helpers import write_config, write_dataset

GT = {"s1": "你好世界", "s2": "发票金额"}


def make_runner(tmp_path, outputs=None, engines=None, **cfg_kwargs) -> Runner:
    ds = write_dataset(tmp_path, GT)
    cfg_path = write_config(
        tmp_path, ds,
        engines=[{"id": "echo", "type": "test.echo"}],
        **cfg_kwargs,
    )
    cfg = load_config(cfg_path)
    if engines is None:
        engines = [EchoEngine("echo", {"outputs": outputs or {}})]
    return Runner(cfg, engines=engines)


def test_run_matrix_and_save(tmp_path) -> None:
    outputs = {"s1": "你好世界", "s2": "发票金"}
    runner = make_runner(tmp_path, outputs)
    run = runner.run()

    assert len(run.predictions) == 2
    by_id = {p.sample_id: p for p in run.predictions}
    assert by_id["s1"].text == "你好世界"
    assert by_id["s2"].error is None

    by_metric = {m.sample_id: m for m in run.metrics}
    assert by_metric["s1"].cer == 0.0
    assert by_metric["s1"].char_recall == 1.0
    assert by_metric["s2"].cer == 0.25
    assert by_metric["s2"].del_rate == 0.25

    run_path = save_run(run, tmp_path / "out", "r1")
    assert run_path == tmp_path / "out" / "r1" / "run.json"
    assert run_path.is_file()
    assert (run_path.parent / "summary.json").is_file()

    reloaded = load_run(run_path)
    assert reloaded.run_name == "t"  # run_name 来自配置，save_run 只决定目录名
    assert len(reloaded.predictions) == 2
    assert reloaded.metrics[0].sample_id == reloaded.predictions[0].sample_id


def test_engine_build_from_config(tmp_path) -> None:
    ds = write_dataset(tmp_path, {"s1": "abc"})
    cfg_path = write_config(
        tmp_path, ds,
        engines=[{
            "id": "echo",
            "type": "test.echo",
            "params": {"outputs": {"s1": "abc"}},
            "cost": {"per_image": 0.5},
        }],
    )
    run = Runner(load_config(cfg_path)).run()
    assert len(run.predictions) == 1
    assert run.predictions[0].cost_usd == 0.5
    assert run.metrics[0].cer == 0.0


def test_unsupported_task_is_skipped(tmp_path) -> None:
    ds = write_dataset(tmp_path, GT)
    cfg_path = write_config(
        tmp_path, ds,
        engines=[{"id": "echo", "type": "test.echo"}],
        tasks=("recognize", "extract"),
        concurrency=1,
    )
    runner = Runner(load_config(cfg_path), engines=[EchoEngine("echo")])
    # 把能力收窄到只支持 recognize
    runner._engines[0].capabilities = ("recognize",)
    runner._engine_map["echo"].capabilities = ("recognize",)
    jobs, skipped = runner.plan()
    assert {j.task for j in jobs} == {"recognize"}
    assert any("任务不支持" in s["reason"] for s in skipped)


def test_modality_mismatch_skips_all_and_raises(tmp_path) -> None:
    ds = write_dataset(tmp_path, GT)
    cfg_path = write_config(
        tmp_path, ds, engines=[{"id": "video", "type": "test.video_only"}]
    )
    runner = Runner(load_config(cfg_path), engines=[VideoOnlyEngine("video")])
    jobs, skipped = runner.plan()
    assert jobs == []
    assert any("模态不匹配" in s["reason"] for s in skipped)
    with pytest.raises(RuntimeError, match="没有可执行的任务组合"):
        runner.run()


def test_error_is_recorded_and_not_scored(tmp_path) -> None:
    engine = EchoEngine("echo", {"fail_times": 10})
    runner = make_runner(tmp_path, engines=[engine])
    run = runner.run()
    assert len(run.predictions) == 2
    assert all(p.error and "模拟第" in p.error for p in run.predictions)
    assert all(m.cer is None for m in run.metrics)
    assert all(m.error for m in run.metrics)


def test_retry_then_success(tmp_path) -> None:
    engine = EchoEngine("echo", {"outputs": GT, "fail_times": 1})
    runner = make_runner(tmp_path, engines=[engine], retries=1, concurrency=1)
    run = runner.run()
    # fail_times=1 是全局只失败第一次：s1 失败后重试成功，s2 一次成功 -> 共 3 次调用
    assert engine.calls == 3
    assert all(p.error is None for p in run.predictions)
    retried = [p for p in run.predictions if "retry_errors" in p.meta]
    assert len(retried) == 1
    assert "模拟第 1 次调用失败" in retried[0].meta["retry_errors"][0]


def test_timeout_recorded_as_error(tmp_path) -> None:
    engine = EchoEngine("echo", {"outputs": GT, "delay_ms": 300})
    runner = make_runner(tmp_path, engines=[engine], timeout_s=0.05, retries=0)
    run = runner.run()
    assert all(p.error and "TimeoutError" in p.error for p in run.predictions)
    assert all(p.latency_ms >= 45 for p in run.predictions)


def test_repeats_use_median_latency(tmp_path) -> None:
    engine = EchoEngine("echo", {"outputs": GT, "delay_ms": 2})
    runner = make_runner(tmp_path, engines=[engine], repeats=3, concurrency=1)
    run = runner.run()
    assert engine.calls == 6  # 2 样本 × 3 次
    for p in run.predictions:
        assert p.meta["repeats"] == 3
        assert len(p.meta["latency_ms_samples"]) == 3
        assert p.cost_usd == 0.0


def test_cache_hit_skips_engine_and_zeroes_latency(tmp_path) -> None:
    engine = EchoEngine("echo", {"outputs": GT})
    runner = make_runner(tmp_path, engines=[engine], cache=True)
    first = runner.run()
    calls_after_first = engine.calls
    assert calls_after_first == 2
    assert all(p.latency_ms > 0 for p in first.predictions)

    second = runner.run()
    assert engine.calls == calls_after_first  # 全部命中缓存
    assert all(p.meta.get("cache_hit") for p in second.predictions)
    assert all(p.latency_ms == 0.0 for p in second.predictions)
    # 指标必须与第一次一致
    assert [m.cer for m in second.metrics] == [m.cer for m in first.metrics]


def test_cache_key_invalidated_by_prompt_and_normalize(tmp_path) -> None:
    cache = PredictionCache(root=tmp_path / "c")
    engine = EchoEngine("echo", {"outputs": GT})
    req = EngineRequest(sample_id="s1", task="recognize")

    k1 = cache.key(engine, req, "digest", NormalizeConfig())
    k2 = cache.key(engine, req, "digest", NormalizeConfig(lower=True))
    req_prompt = EngineRequest(sample_id="s1", task="recognize", prompt="请转录")
    k3 = cache.key(engine, req_prompt, "digest", NormalizeConfig())
    engine2 = EchoEngine("echo", {"outputs": GT, "delay_ms": 1})
    k4 = cache.key(engine2, req, "digest", NormalizeConfig())

    assert len({k1, k2, k3, k4}) == 4


def test_user_visible_config_is_sanitized(tmp_path) -> None:
    ds = write_dataset(tmp_path, {"s1": "abc"})
    cfg_path = write_config(
        tmp_path, ds,
        engines=[{
            "id": "echo",
            "type": "test.echo",
            "params": {"outputs": {"s1": "abc"}, "api_key": "sk-secret"},
        }],
    )
    run = Runner(load_config(cfg_path)).run()
    assert run.config["engines"][0]["params"]["api_key"] == "***"
    dumped = json.dumps(run.to_dict(), ensure_ascii=False)
    assert "sk-secret" not in dumped


def test_plan_is_deterministic(tmp_path) -> None:
    runner = make_runner(tmp_path)
    jobs1, _ = runner.plan()
    jobs2, _ = runner.plan()
    assert jobs1 == jobs2
    assert jobs1 == sorted(jobs1, key=lambda j: (j.engine_id, j.task, j.sample_id))
    assert isinstance(jobs1[0], Job)
