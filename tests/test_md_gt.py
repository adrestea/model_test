"""tools/md_gt.py：从 .md 源文件反推截图标注的对齐逻辑。

不依赖 OCR 引擎：`ocr_image` 在端到端用例里被 monkeypatch 成「返回裁剪后的源文本」，
真实识别质量由 cli 端到端跑（见 STATUS.md O 段），单元测试只锁对齐与边界行为。
"""
from __future__ import annotations

from pathlib import Path

import pytest

import tools.md_gt as md_gt
from tools.md_gt import (
    MIN_COVERAGE,
    build_candidates,
    cer_vs,
    expand_span,
    locate_span,
    main,
    normalize,
)

MD = """# 标题一

> 引用段落：这是一段相当长的说明文字，用来验证跨空行的匹配不会被截断。

---

## 小节标题

| 甲 | 乙 |
|---|---|
| 丙 | 丁 |

第一段正文，内容较多，末尾还有一句收尾的话。

第二段正文。
"""


def _write(tmp_path: Path, text: str = MD) -> Path:
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return p


def _span(md_path: Path, blob: str) -> tuple[int, int, float]:
    joined, starts, lens, _ = build_candidates(md_path)
    return locate_span(joined, starts, lens, normalize(blob))


# ---------------------------------------------------------------- 基础
def test_normalize_removes_whitespace_and_unifies_punct() -> None:
    assert normalize("a b\n\tc") == "abc"
    # NFKC：全角括号/冒号 → 半角
    assert normalize("（甲）：乙") == "(甲):乙"


def test_build_candidates_offsets_are_consistent(tmp_path: Path) -> None:
    md = _write(tmp_path)
    joined, starts, lens, raw = build_candidates(md)
    assert len(starts) == len(lens) == len(raw)
    assert joined == "".join(normalize(x) for x in raw)
    for i, (s, n) in enumerate(zip(starts, lens)):
        assert joined[s:s + n] == normalize(raw[i])


# ---------------------------------------------------------------- 定位
def test_locate_span_finds_paragraph_after_blank_lines(tmp_path: Path) -> None:
    """空行长度为零，块归属不能只看起点，否则会把跨空行的匹配算到上一行。"""
    md = _write(tmp_path)
    _, _, _, raw = build_candidates(md)
    target = next(i for i, line in enumerate(raw) if line.startswith("第二段正文"))
    start, end, cov = _span(md, "第二段正文。")
    assert (start, end) == (target, target)
    assert cov > 0.9


def test_locate_span_covers_multi_line_range(tmp_path: Path) -> None:
    md = _write(tmp_path)
    _, _, _, raw = build_candidates(md)
    blob = "\n".join(raw[4:10])  # --- / 标题 / 空 / 表格三行
    start, end, cov = _span(md, blob)
    assert start <= 4 and end >= 9, f"期望覆盖第 5~10 行，实际 {start}~{end}"
    assert cov >= MIN_COVERAGE


def test_locate_span_rejects_unrelated_text(tmp_path: Path) -> None:
    md = _write(tmp_path)
    start, end, cov = _span(md, "完全无关的另一份文档内容，一个字的交集都没有。")
    assert start < 0 or cov < MIN_COVERAGE


# ---------------------------------------------------------------- 边界补齐
def test_expand_span_pulls_in_continuation_lines(tmp_path: Path) -> None:
    """截图只照到段中间时，要把同段的前后行补进来，避免半句 GT 制造 DEL。"""
    lines = ["# 标题", "", "第一行正文", "第二行正文", "第三行正文", "", "结尾"]
    start, end = expand_span(lines, 2, 3)
    assert (start, end) == (2, 4)


def test_expand_span_stops_at_heading_and_blank(tmp_path: Path) -> None:
    lines = ["# 标题", "正文行", "## 下一个标题", "别的正文"]
    start, end = expand_span(lines, 1, 1)
    assert (start, end) == (1, 1)


# ---------------------------------------------------------------- CER 复核
def test_cer_vs_identical_text_is_zero() -> None:
    assert cer_vs("你好 世界", "你好世界") == 0.0


def test_cer_vs_flags_marker_loss() -> None:
    """源码视图里的 `|` `` ` `` 被漏读，应体现在 CER 上（说明标准答案不是引擎自己写的）。"""
    gt = "| 甲 | `code` |\n|---|---|"
    assert cer_vs(gt, "丨甲丨code丨") > 0.1


# ---------------------------------------------------------------- 端到端（假 OCR）
def _make_dataset(tmp_path: Path) -> Path:
    ds = tmp_path / "datasets" / "shot"
    (ds / "images").mkdir(parents=True)
    (ds / "labels").mkdir()
    (ds / "images" / "s1.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # 只占位，不真读
    (ds / "markdown").mkdir()
    (ds / "markdown" / "doc.md").write_text(MD, encoding="utf-8")
    return ds


def test_main_writes_label_from_markdown_span(tmp_path: Path, monkeypatch) -> None:
    ds = _make_dataset(tmp_path)
    md = ds / "markdown" / "doc.md"
    _, _, _, raw = build_candidates(md)
    fake = normalize("\n".join(raw[4:10]))
    monkeypatch.setattr(md_gt, "ocr_image", lambda p: fake)

    code = main(["--dataset", str(ds)])
    assert code == 0
    label = (ds / "labels" / "s1.txt").read_text(encoding="utf-8")
    assert "小节标题" in label and "| 甲 | 乙 |" in label


def test_main_dry_run_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    ds = _make_dataset(tmp_path)
    md = ds / "markdown" / "doc.md"
    _, _, _, raw = build_candidates(md)
    monkeypatch.setattr(md_gt, "ocr_image", lambda p: normalize("\n".join(raw[4:10])))

    assert main(["--dataset", str(ds), "--dry-run"]) == 0
    assert not (ds / "labels" / "s1.txt").exists()


def test_main_skips_existing_label_without_overwrite(tmp_path: Path, monkeypatch) -> None:
    ds = _make_dataset(tmp_path)
    md = ds / "markdown" / "doc.md"
    _, _, _, raw = build_candidates(md)
    monkeypatch.setattr(md_gt, "ocr_image", lambda p: normalize("\n".join(raw[4:10])))
    out = ds / "labels" / "s1.txt"
    out.write_text("人工标注", encoding="utf-8")

    assert main(["--dataset", str(ds)]) == 0
    assert out.read_text(encoding="utf-8") == "人工标注"


@pytest.mark.parametrize("blob", ["", "毫无关联的文字内容"])
def test_main_fails_on_unmatchable_ocr(tmp_path: Path, monkeypatch, blob: str) -> None:
    ds = _make_dataset(tmp_path)
    if blob:
        # 有文字但对不上 → 覆盖率不足 → 失败
        monkeypatch.setattr(md_gt, "ocr_image", lambda p: normalize(blob))
    else:
        monkeypatch.setattr(md_gt, "ocr_image", lambda p: "")
    assert main(["--dataset", str(ds)]) == 1
    assert not (ds / "labels" / "s1.txt").exists()
