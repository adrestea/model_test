"""端到端链路测试：数据/引擎 -> run -> 落盘 -> 报告渲染。

两类路径：
  - 合成数据（假引擎，无模型依赖，CI 稳定）全链路
  - 现有 datasets/smoke（真 RapidOCR，缺依赖时自动 skip）全链路
"""
from __future__ import annotations

from pathlib import Path

import pytest

import tests.fake_engines  # noqa: F401 - 触发 test.echo 注册
from core.config import load_config
from report.loader import load_run as report_load_run
from report.render import render_all
from runner.run import Runner, save_run
from tests.fake_engines import EchoEngine
from tests.helpers import write_config, write_dataset


def test_synthetic_full_pipeline(tmp_path) -> None:
    """合成数据 + 假引擎 -> run -> save -> 三种报告格式落盘。"""
    ds = write_dataset(tmp_path, {"s1": "你好世界", "s2": "发票金额"})
    cfg_path = write_config(
        tmp_path, ds,
        engines=[{
            "id": "echo",
            "type": "test.echo",
            "params": {"outputs": {"s1": "你好世界", "s2": "发票金额"}},
        }],
        out_dir=str(tmp_path / "results"),
    )
    cfg = load_config(cfg_path)
    runner = Runner(cfg, engines=[EchoEngine("echo", {
        "outputs": {"s1": "你好世界", "s2": "发票金额"},
    })])
    run = runner.run()
    assert all(p.error is None for p in run.predictions)
    assert all(m.cer == 0.0 for m in run.metrics)

    run_path = save_run(run, tmp_path / "results", "r1")
    assert run_path.is_file()

    rendered = render_all(run_path, tmp_path / "report")
    assert rendered["html"].is_file()
    assert rendered["md"].is_file()
    assert (tmp_path / "report" / "engines.csv").is_file()
    assert (tmp_path / "report" / "samples.csv").is_file()

    md = rendered["md"].read_text(encoding="utf-8")
    assert "echo" in md
    assert "100.00%" in md


def test_smoke_dataset_full_pipeline(tmp_path) -> None:
    """用现有 datasets/smoke + 真实 RapidOCR 跑完整链路（无模型环境自动 skip）。"""
    rapidocr = pytest.importorskip("rapidocr_onnxruntime")
    assert rapidocr is not None

    smoke_root = Path("datasets/smoke")
    if not (smoke_root / "images").is_dir():
        pytest.skip("datasets/smoke 不在当前工作目录")

    cfg_path = write_config(
        tmp_path, smoke_root,
        engines=[{"id": "rapidocr", "type": "ocr.rapidocr", "params": {"device": "cpu"}}],
        normalize={"strip_whitespace": True, "unify_punct": True},
        out_dir=str(tmp_path / "results"),
    )
    cfg = load_config(cfg_path)
    run = Runner(cfg).run()
    assert len(run.predictions) >= 3
    assert all(p.error is None for p in run.predictions)

    run_path = save_run(run, tmp_path / "results", "smoke-e2e")
    rendered = render_all(run_path, tmp_path / "report")
    assert rendered["html"].is_file()
    md = rendered["md"].read_text(encoding="utf-8")
    assert "rapidocr" in md

    # report.loader 也应能直接读 run.json（报告层只吃 RunResult，不重新推理）
    reloaded = report_load_run(run_path)
    assert reloaded.run_name == run.run_name