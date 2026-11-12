"""图片缩略图 → base64 data URI。

报告必须单文件自包含（不许 CDN、不许外链），所以图片一律转 base64 内嵌。
体积控制：默认最长边 420px、JPEG q=72，一张票据缩略图约 20–40 KB。
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from report.format import esc

_PLACEHOLDER = (
    '<div class="thumb-missing">无原图<br><span>（样本媒体文件未找到）</span></div>'
)


def pil_available() -> bool:
    try:
        import PIL  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def thumbnail_data_uri(path: str | Path | None, max_px: int = 420,
                       quality: int = 72) -> str | None:
    """生成 data URI；失败返回 None（报告降级成占位块，不抛异常）。"""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        from PIL import Image

        with Image.open(p) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, max_px / max(w, h)) if max(w, h) > 0 else 1.0
            if scale < 1.0:
                im = im.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:  # noqa: BLE001 - 单张图坏了不该让整份报告失败
        return None


def thumb_block(path: str | Path | None, caption: str = "",
                max_px: int = 420, quality: int = 72) -> str:
    """把图片包成 HTML 块；没有图片时给占位块。"""
    uri = thumbnail_data_uri(path, max_px=max_px, quality=quality)
    if uri is None:
        return _PLACEHOLDER
    cap = f'<div class="thumb-cap">{esc(caption)}</div>' if caption else ""
    return (
        f'<figure class="thumb"><img src="{uri}" alt="{esc(caption) or "样本原图"}">'
        f"{cap}</figure>"
    )
