"""传统 OCR adapter 公共工具。

被 adapters/ocr_*.py 复用；文件名以 `_` 开头，`load_builtin_adapters()`
不会把它当成一个引擎模块导入（不需要注册）。

这里只放**无三方依赖**的逻辑（图片路径解析、多边形→Box、行文本拼接），
任何三方库的 import 一律放在各 adapter 的 `_load()` 里，保证
"依赖缺失时不注册失败、只在真正推理时抛中文安装提示"。
"""
from __future__ import annotations

import base64
import contextlib
import os
import tempfile
from typing import Any, Iterable, Iterator, Sequence

from core.types import Box, EngineRequest, Line


# --------------------------------------------------------------------------
# 图片来源
# --------------------------------------------------------------------------
@contextlib.contextmanager
def image_file(req: EngineRequest) -> Iterator[str]:
    """把 EngineRequest 解析成本地图片路径。

    - media_path 存在 → 直接复用，不复制
    - 只有 media_bytes → 落到临时文件（多数 OCR SDK 只吃路径）

    结束后清理临时文件，避免长时间评测堆积。
    """
    path = req.media_path
    if path:
        p = os.path.expanduser(str(path))
        if not os.path.isfile(p):
            raise FileNotFoundError(f"图片文件不存在: {p}")
        yield p
        return

    data = req.media_bytes
    if not data:
        raise ValueError("请求里既没有 media_path 也没有 media_bytes，无法识别")

    suffix = _guess_suffix(data)
    fd, tmp = tempfile.mkstemp(prefix="ocr_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        yield tmp
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def _guess_suffix(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return ".png"


def image_size(path: str) -> tuple[int, int] | None:
    """尽力读 (width, height)；Pillow 缺失/文件损坏时返回 None。"""
    try:
        from PIL import Image  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    try:
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:  # noqa: BLE001
        return None


def read_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


# --------------------------------------------------------------------------
# 几何
# --------------------------------------------------------------------------
def poly_to_box(points: Any) -> Box | None:
    """四边形 / 四点列表 / [x1,y1,x2,y2] → 轴对齐 Box。"""
    if points is None:
        return None
    box = Box.from_any(points)
    if box is not None:
        return box
    # 少数 SDK 返回 [{"X":..}] 的 dict 列表或 numpy 结构
    try:
        xs: list[float] = []
        ys: list[float] = []
        for p in points:
            if isinstance(p, dict):
                xs.append(float(p.get("x", p.get("X", 0))))
                ys.append(float(p.get("y", p.get("Y", 0))))
            else:
                xs.append(float(p[0]))
                ys.append(float(p[1]))
        if xs and ys:
            return Box(min(xs), min(ys), max(xs), max(ys))
    except Exception:  # noqa: BLE001
        return None
    return None


def rect_to_box(left: Any, top: Any, width: Any, height: Any) -> Box | None:
    try:
        x, y = float(left), float(top)
        return Box(x, y, x + float(width), y + float(height))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 文本
# --------------------------------------------------------------------------
def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x30FF      # 日文假名
        or 0xAC00 <= code <= 0xD7AF      # 韩文
        or 0x3000 <= code <= 0x303F      # CJK 标点
        or 0xFF00 <= code <= 0xFFEF      # 全角
    )


def join_words(words: Sequence[str]) -> str:
    """把同一行的词拼成文本：中文之间不加空格，西文单词之间加一个空格。"""
    out = ""
    for w in words:
        w = (w or "").strip()
        if not w:
            continue
        if not out:
            out = w
            continue
        if _is_cjk(out[-1]) or _is_cjk(w[0]):
            out += w          # 中文/全角相邻不加空格
        else:
            out += " " + w
    return out


def lines_to_text(lines: Iterable[Line]) -> str:
    """下游要的全文：按行用 \\n 拼接（阅读顺序由 adapter 保证）。"""
    return "\n".join(l.text for l in lines if l.text and l.text.strip())


# --------------------------------------------------------------------------
# 依赖装载：中文错误提示
# --------------------------------------------------------------------------
def require_module(module: str, install_cmd: str, why: str = "") -> Any:
    """导入三方库；失败时抛带安装命令的中文错误。

    故意不在模块顶层 import：这样 adapter 总能注册成功，
    `veval run` 里缺依赖只会让该引擎的样本报错（error 字段），
    而不是整个引擎类型消失。
    """
    import importlib  # noqa: PLC0415

    try:
        return importlib.import_module(module)
    except Exception as e:  # noqa: BLE001
        hint = f"{why}\n" if why else ""
        raise RuntimeError(
            f"缺少依赖 {module}（{type(e).__name__}: {e}）。\n"
            f"{hint}请先安装：\n    {install_cmd}"
        ) from e


def require_binary(name: str, install_cmd: str, why: str = "") -> str:
    """检查系统可执行文件（如 tesseract CLI）。"""
    import shutil  # noqa: PLC0415

    path = shutil.which(name)
    if not path:
        hint = f"{why}\n" if why else ""
        raise RuntimeError(
            f"找不到可执行文件 `{name}`。\n{hint}请先安装：\n    {install_cmd}"
        )
    return path


def require_env(name: str, why: str = "") -> str:
    """读取环境变量；缺失时抛中文错误（点名缺的是哪个变量）。"""
    val = os.environ.get(name, "").strip()
    if not val:
        hint = f"（{why}）" if why else ""
        raise RuntimeError(
            f"缺少环境变量 {name}{hint}。\n"
            f"请先 export {name}=<你的凭据>，或在 configs/*.yaml 的 params 里"
            f"用对应的 *_env 键指向别的变量名。"
        )
    return val
