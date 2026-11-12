"""报告共用格式化：数字 → 中文表格里该有的样子。

统一放这里，保证 HTML / Markdown / CSV 三种产物的数字口径一致。
"""
from __future__ import annotations

import html


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value: float | None, digits: int = 2) -> str:
    """比率 → 百分数（0.9832 → '98.32%'）。None → '—'。"""
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%"


def rate(value: float | None, digits: int = 2) -> str:
    """错误率 → 百分数，和 pct 同形但语义是"越低越好"。"""
    return pct(value, digits)


def ms(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f} ms"


def money(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "—"
    return f"${value:,.{digits}f}"


def money_display(value: float | None, rmb: float, digits: int = 4) -> str:
    """美元 + 人民币双币展示。"""
    if value is None:
        return "—"
    return f"${value:,.{digits}f} / ¥{value * rmb:,.{digits}f}"


def num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"


def throughput(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.1f} 张/分钟"


def truncate(text: str | None, limit: int = 60) -> str:
    s = (text or "").replace("\n", " ⏎ ")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def pct_or_dash(value: float | None) -> str:
    return "—" if value is None else pct(value)
