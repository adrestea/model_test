"""文本归一化与字符级编辑距离拆解。

CER 的分子必须拆开才有选型价值：
  SUB  错认：GT 有该字，预测成别的字
  DEL  漏提：GT 有该字，预测没有（OCR 典型错误）
  INS  多提：预测多出 GT 没有的字（大模型幻觉典型错误）

本模块只做纯计算，不做 IO，也不依赖任何三方库。
"""
from __future__ import annotations

import unicodedata
from array import array
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizeConfig:
    """文本归一化口径。同一份配置同时作用于 GT 与预测，保证口径一致。"""

    strip_whitespace: bool = True   # 去掉所有空白（换行/空格/制表），CER 按字符算
    lower: bool = False             # 统一小写（英文场景）
    unify_punct: bool = True        # NFKC：全角标点/数字/字母 → 半角
    drop_punct: bool = False        # 去掉 Unicode 标点（严谨口径应关闭）

    @classmethod
    def from_dict(cls, d: dict | None) -> "NormalizeConfig":
        d = d or {}
        return cls(
            strip_whitespace=bool(d.get("strip_whitespace", True)),
            lower=bool(d.get("lower", False)),
            unify_punct=bool(d.get("unify_punct", True)),
            drop_punct=bool(d.get("drop_punct", False)),
        )

    def to_dict(self) -> dict:
        return {
            "strip_whitespace": self.strip_whitespace,
            "lower": self.lower,
            "unify_punct": self.unify_punct,
            "drop_punct": self.drop_punct,
        }

    def apply(self, text: str | None) -> str:
        s = text or ""
        if self.unify_punct:
            # NFKC 同时处理全角标点与全角字母数字，比手工映射表更稳
            s = unicodedata.normalize("NFKC", s)
        if self.lower:
            s = s.lower()
        if self.strip_whitespace:
            s = "".join(ch for ch in s if not ch.isspace())
        if self.drop_punct:
            s = "".join(
                ch for ch in s if not unicodedata.category(ch).startswith("P")
            )
        return s


@dataclass(frozen=True)
class EditStats:
    """一次字符级编辑距离拆解结果。"""

    distance: int
    sub: int
    delete: int
    insert: int
    ref_len: int
    hyp_len: int

    def _rate(self, n: int) -> float:
        if self.ref_len > 0:
            return n / self.ref_len
        # GT 为空：预测也为空记 0，否则按"全错"记 1，避免除零放大
        return 0.0 if self.hyp_len == 0 else 1.0

    @property
    def cer(self) -> float:
        """字符错误率 = (SUB + DEL + INS) / len(GT)。"""
        return self._rate(self.distance)

    @property
    def sub_rate(self) -> float:
        return self._rate(self.sub)

    @property
    def del_rate(self) -> float:
        return self._rate(self.delete)

    @property
    def ins_rate(self) -> float:
        return self._rate(self.insert)

    @property
    def char_recall(self) -> float:
        """完整率 = 1 - DEL - SUB = (len(GT) - DEL - SUB) / len(GT)。"""
        return max(0.0, min(1.0, 1.0 - self.del_rate - self.sub_rate))

    @property
    def exact_match(self) -> float:
        return 1.0 if self.distance == 0 else 0.0


@dataclass(frozen=True)
class EditOp:
    """对齐后的单步编辑操作，供报告层渲染 diff。"""

    op: str          # equal / sub / del / ins
    ref: str = ""    # GT 侧字符
    hyp: str = ""    # 预测侧字符


def _dp_matrices(ref: str, hyp: str) -> tuple[list[array], list[array]]:
    """返回 (编辑距离矩阵, 最少 SUB 数矩阵)。

    同距离下优先最少 SUB（等价于最大化逐字匹配），保证 SUB/DEL/INS
    拆解结果稳定可复现，不因回溯顺序不同而漂移。
    """
    m, n = len(ref), len(hyp)
    dists: list[array] = [array("I", range(n + 1))]
    subs: list[array] = [array("I", [0]) * (n + 1)]
    for i in range(1, m + 1):
        prev_d, prev_s = dists[i - 1], subs[i - 1]
        cur_d = array("I", [0]) * (n + 1)
        cur_s = array("I", [0]) * (n + 1)
        cur_d[0] = i
        rc = ref[i - 1]
        for j in range(1, n + 1):
            if rc == hyp[j - 1]:
                cur_d[j] = prev_d[j - 1]
                cur_s[j] = prev_s[j - 1]
                continue
            # 候选：(距离, SUB 数) 二元组，按字典序取最小
            best_d = prev_d[j - 1] + 1   # 替换
            best_s = prev_s[j - 1] + 1
            if (prev_d[j] + 1, prev_s[j]) < (best_d, best_s):
                best_d, best_s = prev_d[j] + 1, prev_s[j]        # 漏提
            if (cur_d[j - 1] + 1, cur_s[j - 1]) < (best_d, best_s):
                best_d, best_s = cur_d[j - 1] + 1, cur_s[j - 1]  # 多提
            cur_d[j] = best_d
            cur_s[j] = best_s
        dists.append(cur_d)
        subs.append(cur_s)
    return dists, subs


def _backtrack(
    dists: list[array], subs: list[array], ref: str, hyp: str
) -> list[EditOp]:
    """从矩阵右下角回溯，始终选择能保持 (距离, SUB 数) 最优的操作。

    优先 match，其次 SUB、DEL、INS，与 DP 的候选顺序一致，
    这样"认错一个字"记成 1 次错认，而不是同时记一次漏提 + 一次多提。
    """
    i, j = len(ref), len(hyp)
    ops: list[EditOp] = []
    while i > 0 or j > 0:
        cur = (dists[i][j], subs[i][j])
        if (
            i > 0 and j > 0 and ref[i - 1] == hyp[j - 1]
            and cur == (dists[i - 1][j - 1], subs[i - 1][j - 1])
        ):
            ops.append(EditOp("equal", ref[i - 1], hyp[j - 1]))
            i -= 1
            j -= 1
        elif (
            i > 0 and j > 0
            and cur == (dists[i - 1][j - 1] + 1, subs[i - 1][j - 1] + 1)
        ):
            ops.append(EditOp("sub", ref[i - 1], hyp[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and cur == (dists[i - 1][j] + 1, subs[i - 1][j]):
            ops.append(EditOp("del", ref[i - 1], ""))
            i -= 1
        else:
            ops.append(EditOp("ins", "", hyp[j - 1]))
            j -= 1
    ops.reverse()
    return ops


def edit_stats(ref: str | None, hyp: str | None) -> EditStats:
    """对已归一化的两段文本做编辑距离拆解。调用方负责先 apply 归一化。"""
    ref = ref or ""
    hyp = hyp or ""
    if ref == hyp:
        return EditStats(0, 0, 0, 0, len(ref), len(hyp))
    dists, subs = _dp_matrices(ref, hyp)
    ops = _backtrack(dists, subs, ref, hyp)
    sub = sum(1 for o in ops if o.op == "sub")
    delete = sum(1 for o in ops if o.op == "del")
    insert = sum(1 for o in ops if o.op == "ins")
    return EditStats(
        distance=dists[-1][-1],
        sub=sub,
        delete=delete,
        insert=insert,
        ref_len=len(ref),
        hyp_len=len(hyp),
    )


def align(ref: str | None, hyp: str | None) -> list[EditOp]:
    """返回逐字符对齐序列，报告层可据此展示 SUB/DEL/INS 位置。"""
    ref = ref or ""
    hyp = hyp or ""
    dists, subs = _dp_matrices(ref, hyp)
    return _backtrack(dists, subs, ref, hyp)


def split_lines(text: str | None) -> list[str]:
    """把全文切成非空行（已归一化文本用）。"""
    return [ln for ln in (text or "").split("\n") if ln.strip()]
