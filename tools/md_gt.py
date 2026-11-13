"""从原始 Markdown 源文件反推截图标注（L1 全文）。

用途：当语料是「某份 .md 文档的屏幕截图」时，人工转录几十行密集小字既慢又容易错，
而真值其实就在源文件里。本工具只做一件事：

    用能跑通的本地 OCR 把截图里的文字读出来 → 在 .md 源码里定位出「这张截图照的是哪几行」
    → 直接把那几行的**源文本**写成 labels/<stem>.txt

关键点：OCR 只用来**定位行号**，最终标注内容取自 .md 原文，所以不存在「拿被测引擎
自己当标准答案」的循环问题。前提是截图确实是该 .md 的源码视图（`#` / `**` / `|` 可见），
否则定位会失败并明确报错，不会静默产出错误标注。

用法：
    .venv/bin/python tools/md_gt.py --dataset docshot                      # 自动挑 md 文件
    .venv/bin/python tools/md_gt.py --dataset docshot --md path/to/x.md    # 指定 md
    .venv/bin/python tools/md_gt.py --dataset docshot --dry-run            # 只看对齐结果不写文件
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

MD_EXTS = (".md", ".markdown")
IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")

# 对齐质量的及格线：低于此值说明截图不是该 md 的源码视图（可能是渲染视图/别的文档）
MIN_COVERAGE = 0.55


def normalize(s: str) -> str:
    """与评测口径对齐：NFKC + 去所有空白（CER 按字符算，不按行算）。"""
    s = unicodedata.normalize("NFKC", s)
    return "".join(ch for ch in s if not ch.isspace())


def find_project_root() -> Path:
    """以本文件位置为锚点向上找项目根（含 datasets/ 与 core/ 的目录）。"""
    here = Path(__file__).resolve().parent
    for cand in (here, *here.parents):
        if (cand / "datasets").is_dir() and (cand / "core").is_dir():
            return cand
    return Path.cwd()


def ocr_image(path: Path) -> str:
    """用 rapidocr 读图，返回归一化后的整篇文本（仅用于定位）。

    直接传文件路径：RapidOCR 内部走 cv2 读图（BGR），引擎适配器也是这条路径。
    别自己转 RGB 再传数组，两者差 2~4 个百分点的 CER，对不齐评测口径。
    """
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    res, _ = engine(str(path))
    return normalize("".join(text for _, text, _ in res) if res else "")


def locate_span(
    src_norm: str,
    line_starts: list[int],
    line_lens: list[int],
    blob: str,
) -> tuple[int, int, float]:
    """在源文件里找出与截图内容最匹配的连续行范围。

    做法：字符级 SequenceMatcher 对齐 src 与 blob，把每个匹配块覆盖的源字符区间按
    **行区间重叠长度**归属到具体行号（不能只看块起点：空行长度为 0，只看起点会把
    跨空行的长匹配全部算到空行前面那一行上，导致截断）。再按每行被覆盖的比例判定
    该行是否真的出现在截图里。
    """
    from difflib import SequenceMatcher

    if not blob or not src_norm:
        return -1, -1, 0.0

    matcher = SequenceMatcher(None, src_norm, blob, autojunk=False)
    counts = [0] * len(line_starts)
    for b in matcher.get_matching_blocks():
        if b.size < 4:
            continue
        lo, hi = b.a, b.a + b.size
        # 二分定位第一个可能重叠的行
        left, right = 0, len(line_starts) - 1
        while left < right:
            mid = (left + right + 1) // 2
            if line_starts[mid] <= lo:
                left = mid
            else:
                right = mid - 1
        for i in range(left, len(line_starts)):
            seg_lo = line_starts[i]
            seg_hi = seg_lo + line_lens[i]
            if seg_lo >= hi:
                break
            overlap = min(hi, seg_hi) - max(lo, seg_lo)
            if overlap > 0:
                counts[i] += overlap

    visible = [i for i, c in enumerate(counts) if c >= max(3, line_lens[i] * 0.25)]
    if not visible:
        return -1, -1, 0.0
    coverage = min(1.0, sum(counts) / max(1, len(blob)))
    return visible[0], visible[-1], coverage


def build_candidates(md_path: Path) -> tuple[str, list[int], list[int], list[str]]:
    """读 md，返回 (归一化全文, 每行起始偏移, 每行归一化长度, 原始行列表)。"""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    raw_lines = text.splitlines()
    norm_lines = [normalize(line) for line in raw_lines]
    joined = "".join(norm_lines)
    starts: list[int] = []
    lens: list[int] = []
    pos = 0
    for nl in norm_lines:
        starts.append(pos)
        lens.append(len(nl))
        pos += len(nl)
    return joined, starts, lens, raw_lines


def pick_best_md(md_files: list[Path], blob: str) -> tuple[Path, int, int, float] | None:
    """多份 md 时用覆盖率择优。"""
    best = None
    for md in md_files:
        joined, starts, lens, _ = build_candidates(md)
        start, end, cov = locate_span(joined, starts, lens, blob)
        if start < 0:
            continue
        score = cov
        if best is None or score > best[3]:
            best = (md, start, end, score)
    return best


def expand_span(raw_lines: list[str], start: int, end: int) -> tuple[int, int]:
    """把可见范围补全到语义完整的边界。

    截图通常会把一段的中间截断（上下都有半行）。这里只做两件事：
      - 向上补：若起始行的上一行非空且不是标题（说明是同一段的折行），上移
      - 向下补：同理
    避免把半句话当成 GT（那会凭空制造 DEL 错误）。
    """
    def is_heading(s: str) -> bool:
        return s.lstrip().startswith("#")

    while start > 0:
        prev = raw_lines[start - 1]
        if prev.strip() == "" or is_heading(prev) or is_heading(raw_lines[start]):
            break
        start -= 1
    while end < len(raw_lines) - 1:
        nxt = raw_lines[end + 1]
        if nxt.strip() == "" or is_heading(nxt):
            break
        end += 1
    return start, end


def cer_vs(gt: str, blob: str) -> float:
    """快速核对：GT 与 OCR 输出的字符错误率。合理区间约 2%~15%，
    明显低于 1% 说明标注其实是 OCR 自己写的（循环），高于 30% 说明对齐错了文档。"""
    from core.text import edit_stats  # 复用评测口径，避免两套算法

    stats = edit_stats(normalize(gt), blob)
    return stats.cer


def main(argv: list[str] | None = None) -> int:
    root = find_project_root()
    ap = argparse.ArgumentParser(description="从原始 Markdown 反推截图 L1 标注")
    ap.add_argument("--dataset", required=True, help="数据集名（datasets/ 下）或路径")
    ap.add_argument("--md", help="指定 Markdown 源文件；缺省则在 markdown/ 下自动择优")
    ap.add_argument("--md-root", help="Markdown 搜索根目录，默认 datasets/<name>/markdown")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已有标注")
    ap.add_argument("--dry-run", action="store_true", help="只打印对齐结果，不写文件")
    args = ap.parse_args(argv)

    ds = Path(args.dataset)
    ds_dir = ds if ds.is_absolute() or (Path.cwd() / ds).is_dir() else root / "datasets" / args.dataset
    if not ds_dir.is_dir():
        print(f"[错误] 数据集目录不存在：{ds_dir}", file=sys.stderr)
        return 2

    images = sorted(p for p in (ds_dir / "images").rglob("*") if p.suffix.lower() in IMG_EXTS)
    if not images:
        print(f"[错误] {ds_dir / 'images'} 下没有图片", file=sys.stderr)
        return 2

    md_root = Path(args.md_root) if args.md_root else ds_dir / "markdown"
    if args.md:
        md_files = [Path(args.md)]
    else:
        md_files = sorted(p for p in md_root.rglob("*") if p.suffix.lower() in MD_EXTS)
    if not md_files:
        print(f"[错误] 在 {md_root} 下找不到 .md；用 --md 指定源文件", file=sys.stderr)
        return 2
    print(f"数据集 {ds_dir.name}｜图片 {len(images)} 张｜候选 md {len(md_files)} 个")

    labels_dir = ds_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    ok = fail = skip = 0

    for img in images:
        stem = img.stem
        out = labels_dir / f"{stem}.txt"
        if out.exists() and not args.overwrite and not args.dry_run:
            print(f"  [跳过] {stem}：已有标注")
            skip += 1
            continue

        blob = ocr_image(img)
        if not blob:
            print(f"  [失败] {stem}：图里没读到文字")
            fail += 1
            continue

        if args.md:
            best_md = md_files[0]
            joined, starts, lens, raw = build_candidates(best_md)
            start, end, cov = locate_span(joined, starts, lens, blob)
        else:
            picked = pick_best_md(md_files, blob)
            if picked is None:
                print(f"  [失败] {stem}：任何 md 都没对齐上")
                fail += 1
                continue
            best_md, start, end, cov = picked
            _, _, _, raw = build_candidates(best_md)

        if start < 0 or cov < MIN_COVERAGE:
            print(f"  [失败] {stem}：对齐覆盖率仅 {cov:.2f}（阈值 {MIN_COVERAGE}），"
                  f"截图可能不是该 md 的源码视图")
            fail += 1
            continue

        start, end = expand_span(raw, start, end)
        gt = "\n".join(raw[start:end + 1])
        rate = cer_vs(gt, blob)
        rel_md = best_md.relative_to(root) if best_md.is_relative_to(root) else best_md
        print(f"  [OK] {stem}：{rel_md.name} 第 {start + 1}~{end + 1} 行"
              f"（{end - start + 1} 行 / {len(normalize(gt))} 字）"
              f"｜覆盖率 {cov:.2f}｜本地 OCR 对照 CER {rate:.2%}")
        if rate > 0.30:
            print(f"        ⚠ CER 偏高，对齐范围可能不准，请人工过一遍")

        if not args.dry_run:
            out.write_text(gt + "\n", encoding="utf-8")
        ok += 1

    print(f"\n完成：写入 {ok}｜跳过 {skip}｜失败 {fail}"
          + ("（dry-run，未写文件）" if args.dry_run else ""))
    if fail:
        print("提示：可加 --md 指定源文件，或先用 label review 人工校正", file=sys.stderr)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
