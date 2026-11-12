"""core/text.py 的归一化与 CER 拆解测试。"""
from __future__ import annotations

from core.text import EditStats, NormalizeConfig, align, edit_stats, split_lines


def test_normalize_whitespace_and_lower() -> None:
    cfg = NormalizeConfig(
        strip_whitespace=True, lower=True, unify_punct=False, drop_punct=False
    )
    assert cfg.apply(" Hello \n World\t") == "helloworld"


def test_normalize_unify_punct_nfkc() -> None:
    cfg = NormalizeConfig(
        strip_whitespace=True, lower=False, unify_punct=True, drop_punct=False
    )
    # 全角标点/字母/数字统一为半角
    assert cfg.apply("Ａ，Ｂ：１２３") == "A,B:123"


def test_normalize_drop_punct() -> None:
    cfg = NormalizeConfig(
        strip_whitespace=True, lower=False, unify_punct=True, drop_punct=True
    )
    assert cfg.apply("发票，金额：1,234.00。") == "发票金额123400"


def test_normalize_from_dict_defaults() -> None:
    cfg = NormalizeConfig.from_dict(None)
    assert cfg.strip_whitespace is True
    assert cfg.unify_punct is True
    assert cfg.lower is False
    assert cfg.drop_punct is False


def test_edit_stats_substitution() -> None:
    st = edit_stats("abcd", "abxd")
    assert st.distance == 1
    assert (st.sub, st.delete, st.insert) == (1, 0, 0)
    assert st.cer == 0.25
    assert st.char_recall == 0.75


def test_edit_stats_deletion() -> None:
    st = edit_stats("abcd", "abd")
    assert st.distance == 1
    assert (st.sub, st.delete, st.insert) == (0, 1, 0)
    assert st.del_rate == 0.25
    assert st.char_recall == 0.75


def test_edit_stats_insertion() -> None:
    st = edit_stats("abcd", "abxcd")
    assert st.distance == 1
    assert (st.sub, st.delete, st.insert) == (0, 0, 1)
    assert st.ins_rate == 0.25
    # 完整率只看 SUB/DEL，多提不影响"该有的字是否提全"
    assert st.char_recall == 1.0


def test_edit_stats_mixed_and_formula() -> None:
    st = edit_stats("abcdefgh", "abXdefhZZ")
    # abcdefgh -> abXdefhZZ：sub 1 (c->X)，del 1 (g)，ins 2 (ZZ)
    assert st.distance == 4
    assert (st.sub, st.delete, st.insert) == (1, 1, 2)
    assert st.cer == 0.5
    assert st.sub_rate == 0.125
    assert st.del_rate == 0.125
    assert st.ins_rate == 0.25
    assert st.char_recall == 1 - st.del_rate - st.sub_rate
    assert st.exact_match == 0.0


def test_edit_stats_identical_and_empty() -> None:
    same = edit_stats("中文", "中文")
    assert same.distance == 0
    assert same.exact_match == 1.0
    assert same.cer == 0.0

    empty_ref = edit_stats("", "")
    assert empty_ref.cer == 0.0
    assert empty_ref.char_recall == 1.0

    # GT 为空但预测有内容：按"全错"记 1，避免除零
    empty_ref_pred = edit_stats("", "多余")
    assert empty_ref_pred.cer == 1.0
    assert empty_ref_pred.ins_rate == 1.0


def test_edit_stats_cer_equals_rate_sum() -> None:
    st = EditStats(distance=7, sub=2, delete=3, insert=2, ref_len=10, hyp_len=9)
    assert abs(st.cer - (st.sub_rate + st.del_rate + st.ins_rate)) < 1e-12


def test_align_ops() -> None:
    ops = align("abcd", "abXd")
    assert [o.op for o in ops] == ["equal", "equal", "sub", "equal"]
    assert ops[2].ref == "c"
    assert ops[2].hyp == "X"

    ops2 = align("ab", "a")
    assert [o.op for o in ops2] == ["equal", "del"]


def test_split_lines() -> None:
    assert split_lines("第一行\n\n第二行\n") == ["第一行", "第二行"]
    assert split_lines(None) == []
