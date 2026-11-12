"""CLI 端到端测试：run → baseline freeze → baseline diff。"""
from __future__ import annotations

import json

import pytest

import tests.fake_engines  # noqa: F401 - 触发引擎注册
from cli import main
from tests.helpers import write_config, write_dataset

GT = {"s1": "你好世界", "s2": "发票金额"}


def setup_workspace(tmp_path, outputs=None) -> object:
    ds = write_dataset(tmp_path, GT)
    return write_config(
        tmp_path, ds,
        engines=[{
            "id": "echo",
            "type": "test.echo",
            "params": {"outputs": outputs or GT},
        }],
        out_dir=str(tmp_path / "results"),
    )


def test_cli_run_freeze_diff(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = setup_workspace(tmp_path)

    assert main(["run", "-c", str(cfg), "--run-name", "r1", "-q"]) == 0
    run_path = tmp_path / "results" / "r1" / "run.json"
    assert run_path.is_file()
    out = capsys.readouterr().out
    assert "运行完成" in out
    assert "CER" in out
    assert "结果已落盘" in out

    assert main(["baseline", "freeze", str(run_path)]) == 0
    baseline_path = tmp_path / "results" / "baselines" / "r1.json"
    assert baseline_path.is_file()
    assert "基线已冻结" in capsys.readouterr().out

    assert main(["baseline", "diff", str(run_path), "r1"]) == 0
    diff_out = capsys.readouterr().out
    assert "基线对比" in diff_out
    assert "样本级变化" in diff_out
    assert "持平" in diff_out


def test_cli_diff_json(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = setup_workspace(tmp_path)
    assert main(["run", "-c", str(cfg), "--run-name", "r1", "-q"]) == 0
    assert main(["baseline", "freeze", "r1"]) == 0
    capsys.readouterr()  # 清掉 freeze 的人类可读输出，--json 必须只有 JSON

    assert main(["baseline", "diff", "r1", "r1", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_name"] == "r1"
    assert any(row["metric"] == "cer" for row in payload["metric_rows"])
    assert payload["sample_changes"]["counts"]["持平"] == 2


def test_cli_limit_and_engine_filter(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = setup_workspace(tmp_path)
    assert main([
        "run", "-c", str(cfg), "--run-name", "limited",
        "--limit", "1", "--engines", "echo", "-q",
    ]) == 0
    run = json.loads((tmp_path / "results" / "limited" / "run.json").read_text(encoding="utf-8"))
    assert len(run["predictions"]) == 1
    assert run["predictions"][0]["sample_id"] == "s1"
    assert run["predictions"][0]["engine_id"] == "echo"
    capsys.readouterr()


def test_cli_errors_return_nonzero(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = setup_workspace(tmp_path)
    capsys.readouterr()

    assert main(["run", "-c", str(tmp_path / "missing.yaml")]) == 1
    assert "错误" in capsys.readouterr().err

    assert main(["run", "-c", str(cfg), "--engines", "nope", "-q"]) == 1
    assert "没有这些引擎" in capsys.readouterr().err

    assert main(["baseline", "diff", "nope", "nope"]) == 1
    assert "找不到" in capsys.readouterr().err


def test_cli_diff_shows_regression(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = setup_workspace(tmp_path)
    assert main(["run", "-c", str(cfg), "--run-name", "base", "-q"]) == 0
    assert main(["baseline", "freeze", "base"]) == 0
    capsys.readouterr()

    # 第二次结果变差：s1 少一个字
    worse = {"s1": "你好世", "s2": "发票金额"}
    cfg2 = setup_workspace(tmp_path, outputs=worse)
    assert main(["run", "-c", str(cfg2), "--run-name", "worse", "-q"]) == 0
    assert main(["baseline", "diff", "worse", "base", "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "变坏" in out
    assert "s1" in out
