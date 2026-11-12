"""tools/ 层（synth / inspect / label）与新增 CLI 子命令的端到端测试。

字体相关用例跳过条件：无默认中文字体的环境（CI 精简镜像）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

import tests.fake_engines  # noqa: F401 - 触发 test.echo 引擎注册
from cli import main
from tests.helpers import write_config, write_dataset
from tools.inspect import inspect_dataset
from tools.label import build_review_page, draft_labels, resolve_engine_spec
from tools.synth import (
    DEFAULT_FONT,
    SynthOptions,
    _rotate_expand,
    generate_dataset,
)

needs_font = pytest.mark.skipif(
    not Path(DEFAULT_FONT).is_file(), reason="环境里没有默认中文字体"
)


def _make_synth(root: Path, name: str = "sd", **kw) -> Path:
    """在 root 下生成一个小合成数据集，返回数据集根目录。"""
    opts = SynthOptions(
        name=name, out_root=root, count=kw.pop("count", 3), seed=kw.pop("seed", 7), **kw
    )
    generate_dataset(opts)
    return root / name


# ---------------------------------------------------------------- synth
def test_synth_generates_dataset_and_l2_labels(tmp_path: Path) -> None:
    ds = _make_synth(
        tmp_path, lines=3, jpeg_quality=85, rotate=3.0,
        noise=4.0, blur=0.3, scale=1.5, prefix="doc",
    )
    images = sorted((ds / "images").glob("*.jpg"))
    labels = sorted((ds / "labels").glob("*.json"))
    assert len(images) == 3 and len(labels) == 3
    assert (ds / "meta.yaml").is_file()

    for img_path in images:
        sid = img_path.stem
        label = json.loads((ds / "labels" / f"{sid}.json").read_text(encoding="utf-8"))
        assert len(label["lines"]) == 3                       # 行数与参数一致
        assert label["text"] == "\n".join(l["text"] for l in label["lines"])
        with Image.open(img_path) as im:
            W, H = im.size
        for l in label["lines"]:
            x1, y1, x2, y2 = l["box"]
            # box 是真实像素坐标：整数、有序、在画布内
            assert all(isinstance(v, int) for v in l["box"])
            assert 0 <= x1 < x2 <= W and 0 <= y1 < y2 <= H
        assert label["meta"]["scene"] == "合成"


def test_synth_boxes_cover_ink(tmp_path: Path) -> None:
    """不做任何降质时，GT box 内必须真的有墨迹（box 与像素严格对齐）。"""
    ds = _make_synth(tmp_path, lines=2, name="plain")
    for label_path in sorted((ds / "labels").glob("*.json")):
        img_path = ds / "images" / f"{label_path.stem}.png"
        label = json.loads(label_path.read_text(encoding="utf-8"))
        with Image.open(img_path) as im:
            arr = np.asarray(im)
        for l in label["lines"]:
            x1, y1, x2, y2 = l["box"]
            crop = arr[y1:y2, x1:x2]
            assert crop.size, f"{label_path.stem} box 为空区域"
            assert crop.min() < 128, "box 内没有深色墨迹，box 与像素没对上"
            # box 外紧邻一圈应该几乎是背景（box 没画太大）
            pad = 2
            ring = arr[
                max(0, y1 - pad):min(arr.shape[0], y2 + pad),
                max(0, x1 - pad):min(arr.shape[1], x2 + pad),
            ]
            inner_area = crop.shape[0] * crop.shape[1]
            assert (ring < 128).sum() < inner_area * 0.9


def test_synth_reproducible_with_same_seed(tmp_path: Path) -> None:
    _make_synth(tmp_path, lines=2, name="a", seed=11)
    _make_synth(tmp_path / "b", lines=2, name="a", seed=11)
    for i in range(1, 4):
        f1 = (tmp_path / "a" / "labels" / f"synth_{i:04d}.json").read_text(encoding="utf-8")
        f2 = (tmp_path / "b" / "a" / "labels" / f"synth_{i:04d}.json").read_text(encoding="utf-8")
        assert f1 == f2


def test_rotate_expand_maps_boxes_exactly() -> None:
    """90° 旋转（方画布）时，box 映射必须与像素内容严格一致。"""
    img = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(img).rectangle([10, 10, 30, 30], fill=0)   # 左上角黑方块
    out, boxes = _rotate_expand(img, [(10, 10, 30, 30)], 90.0, fill=255)
    assert out.size == (100, 100)                             # 方画布尺寸不变
    assert boxes == [(10.0, 70.0, 30.0, 90.0)]                 # 逆时针转到左下
    ys, xs = np.where(np.asarray(out) < 128)
    assert abs(xs.min() - 10) <= 2 and abs(ys.min() - 70) <= 2
    assert abs(xs.max() - 30) <= 2 and abs(ys.max() - 90) <= 2


def test_rotate_expand_enlarges_canvas() -> None:
    img = Image.new("L", (200, 100), 255)
    out, boxes = _rotate_expand(img, [(0, 0, 200, 100)], 45.0, fill=255)
    # 200x100 旋转 45° 后画布对角扩大
    assert out.size[0] > 200 and out.size[1] > 100
    assert all(0 <= b[0] and b[2] <= out.size[0] for b in boxes)


def test_synth_refuses_existing_dataset(tmp_path: Path) -> None:
    _make_synth(tmp_path, count=1, name="dup")
    with pytest.raises(FileExistsError):
        _make_synth(tmp_path, count=1, name="dup")


# ---------------------------------------------------------------- inspect
def test_inspect_counts_and_missing_ids(tmp_path: Path) -> None:
    ds = write_dataset(tmp_path, {"s1": "甲", "s2": "乙"})     # 2 张带 txt 标注
    (ds / "images" / "s3.png").write_bytes(b"\x89PNG\r\n\x1a\n")   # 1 张缺标注
    (ds / "labels" / "ghost.json").write_text("{}", encoding="utf-8")  # 孤儿标注
    info = inspect_dataset(str(ds))
    assert info["total"] == 3
    assert info["labeled"] == 2
    assert info["missing_ids"] == ["s3"]
    assert info["orphan_labels"] == ["ghost.json"]
    assert info["coverage"] == pytest.approx(2 / 3)
    assert info["kind_counts"]["L1纯文本"] == 2


def test_inspect_on_l2_dataset(tmp_path: Path) -> None:
    ds = _make_synth(tmp_path, lines=2)
    info = inspect_dataset(str(ds))
    assert info["total"] == 3
    assert info["labeled"] == 3 and info["missing_ids"] == []
    assert info["with_lines"] == 3 and info["with_box"] == 3
    assert info["meta"]["scene"] == "合成"


def test_inspect_missing_dataset(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        inspect_dataset("不存在的数据集", root=tmp_path)


# ---------------------------------------------------------------- label draft
def test_draft_labels_with_echo_engine(tmp_path: Path) -> None:
    ds = write_dataset(tmp_path, {"s1": "x", "s2": "y"})
    spec = {"id": "echo", "type": "test.echo",
            "params": {"outputs": {"s1": "第一行\n第二行", "s2": "只有一行"}}}
    result = draft_labels(str(ds), spec)
    assert result["written"] == ["s1", "s2"] and result["failed"] == []
    label = json.loads((ds / "labels" / "s1.json").read_text(encoding="utf-8"))
    assert [l["text"] for l in label["lines"]] == ["第一行", "第二行"]
    assert label["meta"]["draft"] is True
    assert label["meta"]["engine"] == "echo"

    # 默认跳过已有标注；--overwrite 才覆盖
    again = draft_labels(str(ds), spec)
    assert again["written"] == [] and again["skipped"] == ["s1", "s2"]
    forced = draft_labels(str(ds), spec, overwrite=True)
    assert forced["written"] == ["s1", "s2"]


def test_draft_labels_records_failures(tmp_path: Path) -> None:
    ds = write_dataset(tmp_path, {"s1": "x", "s2": "y"})
    spec = {"id": "boom", "type": "test.echo",
            "params": {"fail_times": 5, "outputs": {"s1": "", "s2": ""}}}
    result = draft_labels(str(ds), spec)
    assert result["written"] == []
    assert {f["sample_id"] for f in result["failed"]} == {"s1", "s2"}
    assert "模拟第 1 次调用失败" in result["failed"][0]["error"]


def test_resolve_engine_spec_sources(tmp_path: Path) -> None:
    ds = write_dataset(tmp_path, {"s1": "x"})
    cfg = write_config(tmp_path, ds, engines=[
        {"id": "e1", "type": "test.echo", "params": {"outputs": {"s1": "A"}}},
        {"id": "e2", "type": "test.echo", "params": {"outputs": {"s1": "B"}}},
    ])
    # 从配置挑引擎
    spec = resolve_engine_spec(config=cfg, engine_id="e2")
    assert spec["id"] == "e2"
    # 类型 + params JSON
    spec = resolve_engine_spec(engine="test.echo", params='{"default_text": "C"}')
    assert spec == {"type": "test.echo", "params": {"default_text": "C"}, "id": "test.echo"}
    # 完整 JSON spec
    spec = resolve_engine_spec(engine='{"type": "test.echo", "id": "d"}')
    assert spec["type"] == "test.echo"
    # 错误输入
    with pytest.raises(ValueError):
        resolve_engine_spec()
    with pytest.raises(ValueError):
        resolve_engine_spec(engine="test.echo", config=cfg)
    with pytest.raises(ValueError):
        resolve_engine_spec(engine="not-json{")


# ---------------------------------------------------------------- label review
def test_review_page_is_self_contained(tmp_path: Path) -> None:
    ds = write_dataset(tmp_path, {"s1": "已有标注", "s2": "x"})
    (ds / "labels" / "s1.json").write_text(
        json.dumps({"text": "已有标注",
                    "lines": [{"text": "已有标注", "box": [1, 2, 300, 40]}]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    page = build_review_page(str(ds), out=tmp_path / "review.html")
    html = page.read_text(encoding="utf-8")
    # 图片 base64 内嵌、样本 ID 齐全
    assert "data:image/png;base64," in html
    assert "s1" in html and "s2" in html
    assert "下载 $" in html                        # 导出按钮（JS 渲染）
    assert '"label_path": "labels/s1.json"' in html   # 每样本标准标注文件名在数据里
    assert "导出全部" in html
    # 零外链：不允许任何 http(s) 资源引用
    assert "http://" not in html and "https://" not in html
    # 内嵌数据可被 JSON.parse：截取 veval-data 块校验
    start = html.index('id="veval-data">') + len('id="veval-data">')
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])
    by_id = {s["id"]: s for s in payload["samples"]}
    assert by_id["s1"]["lines"][0]["box"] == [1.0, 2.0, 300.0, 40.0]
    assert by_id["s2"]["had_label"] is True       # s2 只有 txt 标注
    assert by_id["s1"]["had_label"] is True


def test_review_page_includes_unlabeled_samples(tmp_path: Path) -> None:
    ds = write_dataset(tmp_path, {"s1": "x"})
    (ds / "labels" / "s1.txt").unlink()          # 唯一样本缺标注
    page = build_review_page(str(ds), out=tmp_path / "r.html")
    html = page.read_text(encoding="utf-8")
    start = html.index('id="veval-data">') + len('id="veval-data">')
    payload = json.loads(html[start:html.index("</script>", start)])
    s = payload["samples"][0]
    assert s["had_label"] is False and s["lines"] == []


# ---------------------------------------------------------------- CLI 子命令
def test_cli_synth_then_inspect(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main([
        "synth", "--name", "sd", "--out-root", str(tmp_path),
        "-n", "2", "--lines", "2", "--font-size", "24",
        "--jpeg-quality", "80", "--seed", "3",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "合成完成" in out and "标注抽样" in out
    assert (tmp_path / "sd" / "images").is_dir()
    assert len(list((tmp_path / "sd" / "labels").glob("*.json"))) == 2

    rc = main(["dataset", "inspect", "sd", "--root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "图片数        2" in out
    assert "覆盖率 100%" in out
    assert "含像素 box    2" in out


def test_cli_dataset_inspect_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["dataset", "inspect", "nope", "--root", str(tmp_path)]) == 1
    assert "找不到数据集" in capsys.readouterr().err


def test_cli_label_draft_and_review(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    ds = write_dataset(tmp_path, {"s1": "x"})
    rc = main([
        "label", "draft", str(ds),
        "--engine", "test.echo",
        "--params", '{"outputs": {"s1": "草稿文本"}}',
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "草稿完成" in out and "写入 1" in out
    assert json.loads((ds / "labels" / "s1.json").read_text(encoding="utf-8"))["text"] == "草稿文本"

    rc = main(["label", "review", str(ds), "-o", str(tmp_path / "rev.html")])
    assert rc == 0
    assert "校正页已生成" in capsys.readouterr().out
    assert (tmp_path / "rev.html").is_file()
    assert (tmp_path / "rev.html").read_text(encoding="utf-8").count("s1") >= 2


def test_cli_label_draft_bad_engine(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    ds = write_dataset(tmp_path, {"s1": "x"})
    capsys.readouterr()
    assert main(["label", "draft", str(ds), "--engine", "nope"]) == 1
    assert "未注册的引擎类型" in capsys.readouterr().err


def test_cli_report_renders_all_formats(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    ds = write_dataset(tmp_path, {"s1": "你好世界", "s2": "发票金额"})
    cfg = write_config(
        tmp_path, ds,
        engines=[{"id": "echo", "type": "test.echo",
                  "params": {"outputs": {"s1": "你好世界", "s2": "发票金额"}}}],
        out_dir=str(tmp_path / "results"),
    )
    assert main(["run", "-c", str(cfg), "--run-name", "r1", "-q"]) == 0
    capsys.readouterr()

    rep = tmp_path / "rep"
    rc = main(["report", "r1", "-o", str(rep), "--formats", "html,md,csv"])
    assert rc == 0
    assert "报告已生成" in capsys.readouterr().out
    for name in ("report.html", "report.md", "engines.csv", "samples.csv",
                 "scenes.csv", "costs.csv"):
        assert (rep / name).is_file(), f"缺少 {name}"
