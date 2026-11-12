"""合成数据集生成器：PIL 渲染中文文本图 + 自动产出 L2 标注（真实像素 box）。

设计要点：
  - box 不是"大概画个框"，而是用 draw.textbbox 拿到真实墨迹范围；
    旋转/缩放用同一套仿射数学变换 box，保证 GT 与像素严格对齐。
  - 每张图独立随机种子（seed + 序号），参数一样即可复现。
  - 产物符合 datasets/README.md 规范：
      datasets/<name>/images/<id>.jpg|png + labels/<id>.json + meta.yaml
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# 系统默认中文字体（Noto Sans CJK）；缺失时用户需 --font 指定
DEFAULT_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# 内置语料：单行业务文本，模拟票据/合同/物流等 OCR 常见内容
CORPUS: tuple[str, ...] = (
    "发票号码：12345678",
    "开票日期：2024年05月01日",
    "合计金额：￥1,234.00",
    "收款人：张三",
    "联系电话：138-0000-1111",
    "地址：北京市海淀区中关村大街1号",
    "合同编号：HT-2024-0091",
    "甲方：北京某某科技有限公司",
    "乙方：上海示例信息技术有限公司",
    "订购单号：PO-8839201",
    "交货日期：2024年6月30日",
    "运输方式：公路运输",
    "结算方式：月结30天",
    "开户银行：中国工商银行北京分行",
    "银行账号：6222 0202 0011 2233",
    "纳税人识别号：91110108MA01B2C34D",
    "备注：货到验收合格后付款",
    "单价：人民币叁佰贰拾元整",
    "数量：120件",
    "金额小写：￥38,400.00",
    "经办人：李四",
    "审核人：王五",
    "批准人：赵六",
    "提货地点：上海市浦东新区世纪大道100号",
    "签发日期：2024年3月15日",
    "有效期至：2025年3月14日",
    "产品名称：智能语音识别模块",
    "规格型号：VLM-OCR-3000",
    "生产批号：20240312A7",
    "检验员：钱七",
    "序号：0042",
    "邮政编码：100080",
    "电子邮箱：support@example.com",
    "传真：010-88886666",
    "大写金额：叁万捌仟肆佰元整",
)


@dataclass
class SynthOptions:
    """合成参数（与 CLI 参数一一对应）。"""

    name: str = "synth"                # 数据集名 → datasets/<name>/
    out_root: str | Path = "datasets"  # 数据集根目录
    count: int = 8                      # 生成图片数
    prefix: str = "synth"              # 样本 ID 前缀：<prefix>_0001
    font: str = DEFAULT_FONT
    font_size: int = 32
    lines: int | None = None           # 固定每图行数（优先于 min/max）
    min_lines: int = 2
    max_lines: int = 5
    width: int | None = None           # 固定画布宽（None=按文本自适应）
    height: int | None = None          # 固定画布高
    noise: float = 0.0                 # 高斯噪点 sigma（0=关）
    blur: float = 0.0                  # 高斯模糊半径（0=关）
    rotate: float = 0.0                # 随机旋转幅度 ±deg（0=关）
    jpeg_quality: int | None = None    # None=PNG；给数值则存 JPEG（1-95）
    scale: float = 1.0                 # 整体缩放系数
    seed: int = 42
    bg: int = 255                      # 背景灰度
    extra_meta: dict = field(default_factory=dict)

    def validate(self) -> "SynthOptions":
        if self.count < 1:
            raise ValueError("--count 至少为 1")
        if not Path(self.font).is_file():
            raise FileNotFoundError(
                f"字体文件不存在: {self.font}；请用 --font 指定一个可用的中文 TTC/TTF"
            )
        if self.font_size < 8:
            raise ValueError("字号太小（最少 8）")
        if self.lines is not None:
            if self.lines < 1:
                raise ValueError("--lines 至少为 1")
        elif not (1 <= self.min_lines <= self.max_lines):
            raise ValueError("行数范围不合法：需要 1 <= min_lines <= max_lines")
        if self.noise < 0 or self.blur < 0:
            raise ValueError("噪点/模糊不能为负数")
        if not 0 <= self.rotate <= 45:
            raise ValueError("旋转幅度建议在 0~45 度之间")
        if self.jpeg_quality is not None and not (1 <= self.jpeg_quality <= 95):
            raise ValueError("JPEG 质量取值 1-95")
        if self.scale <= 0:
            raise ValueError("缩放系数必须为正数")
        return self


def _rotate_expand(
    img: Image.Image,
    boxes: list[tuple[float, float, float, float]],
    angle_deg: float,
    fill: int | tuple,
) -> tuple[Image.Image, list[tuple[float, float, float, float]]]:
    """把 img 逆时针旋转 angle_deg 并扩展画布，box 用同一仿射映射变换。

    不直接用 PIL.rotate（内部偏移量难与 box 对齐），而是自己构造输出→输入的
    AFFINE 矩阵，box 用它的逆映射（前向）变换四角后取 AABB，数学上与像素严格一致。
    """
    if not angle_deg:
        return img, boxes
    theta = math.radians(angle_deg)
    # 与 PIL.rotate 一致：把 cos/sin 取整到有限小数位，避免 90° 因 6e-17 的
    # 浮点残量被 ceil 抬成 101px 画布（box 尺寸会跟着差 1px）
    cos = round(math.cos(theta), 12)
    sin = round(math.sin(theta), 12)
    w, h = img.size
    # 输入画布四角做前向旋转，得到扩展后的画布尺寸
    xs, ys = [], []
    for x, y in ((0, 0), (w, 0), (w, h), (0, h)):
        xs.append(cos * x + sin * y)
        ys.append(-sin * x + cos * y)
    W = math.ceil(max(xs)) - math.floor(min(xs))
    H = math.ceil(max(ys)) - math.floor(min(ys))
    icx, icy = w / 2.0, h / 2.0
    ocx, ocy = W / 2.0, H / 2.0
    # PIL AFFINE 六元组给出"输出坐标 → 输入坐标"：x_in = a·x_out + b·y_out + c
    tx = icx - (cos * ocx - sin * ocy)
    ty = icy - (sin * ocx + cos * ocy)
    out = img.transform(
        (W, H), Image.AFFINE, (cos, -sin, tx, sin, cos, ty),
        resample=Image.BICUBIC, fillcolor=fill,
    )
    new_boxes = []
    for x1, y1, x2, y2 in boxes:
        pts = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        nxs = [ocx + cos * (x - icx) + sin * (y - icy) for x, y in pts]
        nys = [ocy - sin * (x - icx) + cos * (y - icy) for x, y in pts]
        new_boxes.append((min(nxs), min(nys), max(nxs), max(nys)))
    return out, new_boxes


def _render_one(
    opts: SynthOptions,
    font: ImageFont.FreeTypeFont,
    rng: random.Random,
    np_rng: np.random.Generator,
) -> tuple[Image.Image, list[dict], list[str]]:
    """渲染单张图，返回 (图像, 行标注列表, 文本列表)。"""
    n_lines = opts.lines if opts.lines is not None else rng.randint(
        opts.min_lines, opts.max_lines
    )
    # 语料行：避免同一张图里出现连续重复行
    texts: list[str] = []
    while len(texts) < n_lines:
        cand = rng.choice(CORPUS)
        if not texts or cand != texts[-1]:
            texts.append(cand)

    # 先在 1x1 画布上量出每行的墨迹尺寸，再定画布大小
    probe = Image.new("L", (8, 8))
    measure = ImageDraw.Draw(probe)
    leading = int(opts.font_size * 1.6)          # 行距
    margin = max(10, opts.font_size // 2)
    widths, heights = [], []
    for t in texts:
        l, t_, r, b = measure.textbbox((0, 0), t, font=font)
        widths.append(r - l)
        heights.append(b - t_)
    natural_w = max(widths) + 2 * margin
    natural_h = n_lines * leading + 2 * margin
    # 固定画布时也不允许小于文本自然尺寸（避免静默截断）
    W = max(int(opts.width or 0), natural_w)
    H = max(int(opts.height or 0), natural_h)

    fg = rng.randint(15, 70)                     # 墨色随机深灰，比纯黑更接近扫描件
    img = Image.new("L", (W, H), opts.bg)
    draw = ImageDraw.Draw(img)
    lines: list[dict] = []
    for i, t in enumerate(texts):
        x, y = margin, margin + i * leading
        draw.text((x, y), t, font=font, fill=fg)
        l, tp, r, b = draw.textbbox((x, y), t, font=font)
        lines.append({"text": t, "box": [float(l), float(tp), float(r), float(b)]})

    # ---- 降质链：旋转 → 缩放 → 模糊 → 噪点（box 同步参与前两步） ----
    if opts.rotate > 0:
        angle = rng.uniform(-opts.rotate, opts.rotate)
        img, boxes = _rotate_expand(img, [tuple(l["box"]) for l in lines], angle, opts.bg)
        for l, nb in zip(lines, boxes):
            l["box"] = [float(v) for v in nb]
    if opts.scale != 1.0:
        sw, sh = max(1, round(img.width * opts.scale)), max(1, round(img.height * opts.scale))
        img = img.resize((sw, sh), Image.LANCZOS)
        for l in lines:
            l["box"] = [v * opts.scale for v in l["box"]]
    if opts.blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(opts.blur))
    if opts.noise > 0:
        arr = np.asarray(img).astype(np.int16)
        arr = np.clip(arr + np_rng.normal(0.0, opts.noise, arr.shape), 0, 255)
        img = Image.fromarray(arr.astype(np.uint8), mode="L")
    return img, lines, texts


def generate_dataset(opts: SynthOptions) -> dict:
    """按参数生成完整数据集目录，返回摘要信息（路径/数量/标注抽样）。"""
    opts.validate()
    root = Path(opts.out_root) / opts.name
    images_dir = root / "images"
    labels_dir = root / "labels"
    if root.exists() and any(images_dir.iterdir() if images_dir.is_dir() else []):
        raise FileExistsError(
            f"数据集目录已存在且不为空: {images_dir}；换个 --name 或先清理目录"
        )
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    font = ImageFont.truetype(opts.font, opts.font_size)
    ext = ".jpg" if opts.jpeg_quality is not None else ".png"
    sample_ids: list[str] = []
    for i in range(opts.count):
        rng = random.Random(opts.seed * 1_000_003 + i)   # 参数一致 → 逐图可复现
        np_rng = np.random.default_rng(opts.seed * 1_000_003 + i)
        sid = f"{opts.prefix}_{i + 1:04d}"
        img, lines, texts = _render_one(opts, font, rng, np_rng)
        img_path = images_dir / f"{sid}{ext}"
        if opts.jpeg_quality is not None:
            img.save(img_path, quality=opts.jpeg_quality)
        else:
            img.save(img_path)
        label = {
            "text": "\n".join(texts),
            "lines": [
                {
                    "text": l["text"],
                    # 真实像素 box 取整；旋转后可能贴边，clamp 到画布内
                    "box": _clamp_box(l["box"], img.width, img.height),
                }
                for l in lines
            ],
            "meta": {
                "scene": "合成",
                "source": "veval synth",
                "image": img_path.name,
            },
        }
        (labels_dir / f"{sid}.json").write_text(
            json.dumps(label, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        sample_ids.append(sid)

    # meta.yaml：记录生成参数，报告层会读它做场景分组
    meta = {
        "lang": "zh",
        "scene": "合成",
        "source": "veval synth（程序合成，非真实扫描）",
        "license": "internal",
        "generator": {
            "tool": "veval synth",
            "font": opts.font,
            "font_size": opts.font_size,
            "lines": opts.lines if opts.lines is not None
            else f"{opts.min_lines}-{opts.max_lines}",
            "noise": opts.noise,
            "blur": opts.blur,
            "rotate": opts.rotate,
            "jpeg_quality": opts.jpeg_quality,
            "scale": opts.scale,
            "seed": opts.seed,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **opts.extra_meta,
        },
    }
    (root / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    first = labels_dir / f"{sample_ids[0]}.json"
    return {
        "name": opts.name,
        "root": root,
        "images_dir": images_dir,
        "labels_dir": labels_dir,
        "meta_path": root / "meta.yaml",
        "count": len(sample_ids),
        "sample_ids": sample_ids,
        "label_sample": json.loads(first.read_text(encoding="utf-8")),
    }


def _clamp_box(box: list[float], w: int, h: int) -> list[int]:
    """box 四值取整并夹回画布内（旋转扩展后可能差半像素出界）。"""
    x1, y1, x2, y2 = box
    x1, x2 = sorted((max(0, round(x1)), min(w, round(x2))))
    y1, y2 = sorted((max(0, round(y1)), min(h, round(y2))))
    return [x1, y1, x2, y2]
