"""生成 OCR adapter 自测用的票据样张（无隐私、可复现）。

用法：
    .venv/bin/python tests/assets/gen_sample.py

输出：
    tests/assets/ocr_sample.png     A4@150dpi 中文增值税发票样张（干净扫描件）
    tests/assets/ocr_sample_photo.jpg  同一张内容，加噪+轻微倾斜+JPEG 压缩（模拟拍照件）

只是"造图脚本"，不是引擎依赖。图片本身已提交到仓库，跑测试不需要重跑本脚本。
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONT_REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

# 样张内容：字段刻意包含中文/数字/标点/全角，方便验证 CER 与行级输出
LINES: list[tuple[str, int, int, str]] = [
    ("增值税电子普通发票", 420, 110, "bold"),
    ("发票代码：011002100311", 120, 230, "reg"),
    ("发票号码：12345678", 120, 290, "reg"),
    ("开票日期：2024年05月01日", 120, 350, "reg"),
    ("购买方名称：北京示例科技有限公司", 120, 420, "reg"),
    ("纳税人识别号：91110108MA01ABCD2X", 120, 480, "reg"),
    ("货物或应税劳务名称：技术服务费", 120, 570, "reg"),
    ("数量：1    单价：1000.00    金额：1000.00", 120, 630, "reg"),
    ("税率：6%    税额：60.00", 120, 690, "reg"),
    ("价税合计（大写）：壹仟零陆拾元整", 120, 780, "reg"),
    ("（小写）￥1060.00", 120, 840, "reg"),
    ("销售方名称：上海测试信息技术有限公司", 120, 930, "reg"),
    ("备注：本图片由 PIL 渲染生成，仅用于 OCR adapter 自测", 120, 1020, "reg"),
]


def render() -> Image.Image:
    img = Image.new("RGB", (1240, 1400), "white")
    draw = ImageDraw.Draw(img)
    for text, x, y, weight in LINES:
        path = FONT_BOLD if weight == "bold" else FONT_REG
        size = 52 if weight == "bold" else 36
        font = ImageFont.truetype(path, size)
        draw.text((x, y), text, fill="black", font=font)
    return img


def photo_like(img: Image.Image) -> Image.Image:
    rnd = random.Random(20240501)
    out = img.rotate(-1.2, expand=True, fillcolor="white", resample=Image.BICUBIC)
    px = out.load()
    for _ in range(out.width * out.height // 6):        # 轻噪点
        x, y = rnd.randrange(out.width), rnd.randrange(out.height)
        v = rnd.randint(200, 255)
        px[x, y] = (v, v, v)
    return out.filter(ImageFilter.GaussianBlur(0.6))


def main() -> None:
    img = render()
    png = HERE / "ocr_sample.png"
    img.save(png, "PNG")
    jpg = HERE / "ocr_sample_photo.jpg"
    photo_like(img).save(jpg, "JPEG", quality=72)
    print(f"written: {png} ({png.stat().st_size} bytes)")
    print(f"written: {jpg} ({jpg.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
