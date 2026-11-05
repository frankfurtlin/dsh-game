"""结算明细测试: result 里的 winners / payouts / pots / ranks / tie 必须说清
「谁赢了、谁跟谁平、各拿多少」—— 前端结算弹窗与平局文案全靠这几个字段。

为什么要单独测：旧版 result 只有一个扁平的 winners 列表，前端只能写
「平局，平分底池」（多人拿钱 ≠ 平局，边池会让不同人各赢一层，而且各拿的钱不同）。
这里用**固定牌堆**构造确定性牌局，不依赖随机发牌：
  · 公共牌即同花顺 → 两家必然摊牌平局（点名是哪几家平）
  · 三家不同筹码全下 → 主池/边池由不同人赢下（不是平局）
  · 两人平局 + 奇数底池 → 多出的 1 个筹码只给一家（金额不能四舍五入成"平分"）
  · 对手弃牌 → 不摊牌，没有牌型，整池归赢家
  · 随机自搏 → payouts 必须恰好等于底池（筹码守恒）
"""
import random

from .cards import Card, make_deck
from .game import Hand, Action

# 公共牌 = 皇家同花顺：任何两手牌都只能打公共牌 → 必然同牌型平局
ROYAL = ("As", "Ks", "Qs", "Js", "Ts")


def _deck(codes):
    """按「发牌顺序」给牌：Hand 用 deck.pop()（从末尾取），所以这里倒着放。

    codes 的约定：各座位 2 张（按座位序）→ 公共牌 5 张（翻牌 3 + 转牌 + 河牌）。
    """
    return [Card(c) for c in reversed(codes)]


def _all_in_showdown(stacks, deck_codes, button=0, sb=1, bb=2):
    """所有人翻牌前全下，跑到摊牌（牌堆顺序：各座位 2 张，然后 5 张公共牌）。"""
    g = Hand(list(stacks), button=button, sb=sb, bb=bb, deck=_deck(deck_codes))
    guard = 0
    while g.to_act is not None and guard < 40:
        i = g.to_act
        acts = g.legal_actions()
        # 能全下就全下，否则跟注（构造 100% 摊牌的确定性牌局）
        a = next((x for x in acts if x.kind == "raise" and x.is_allin), None)
        if a is None:
            a = next((x for x in acts if x.kind == "call"), None)
        assert a is not None, f"座位{i} 没有可用的全下/跟注: {acts}"
        g.apply(a)
        guard += 1
    assert g.result is not None, "未结算"
    return g


def test_board_plays_tie_names_both_winners():
    """两家都打公共牌 → 平局：winners 点出两家，pots[0].split=True。"""
    deck = ["2h", "3d", "4c", "5h"] + list(ROYAL)      # P0=2h3d  P1=4c5h
    g = _all_in_showdown([200, 200], deck)
    r = g.result
    assert r["winners"] == [0, 1], r
    assert r["tie"] is True, "公共牌成牌的两家必须是平局"
    assert r["payouts"] == [200, 200], r
    assert sum(r["payouts"]) == r["pot"] == 400
    assert len(r["pots"]) == 1 and r["pots"][0]["split"] is True, r["pots"]
    assert r["ranks"] == {"0": "同花顺", "1": "同花顺"}, r["ranks"]
    assert sum(g.stacks) == 400, f"筹码不守恒 {g.stacks}"
    print(f"  [ok] 公共牌平局 -> winners={r['winners']} payouts={r['payouts']} "
          f"ranks={r['ranks']}")


def test_side_pots_are_not_a_tie():
    """三家不同筹码全下：主池归 AA，边池归 KK —— 多人拿钱但不是平局。"""
    deck = ["As", "Ah", "Ks", "Kh", "Qs", "Qh",
            "2c", "3d", "7h", "9s", "Jc"]            # 公共牌无同花/顺子可能
    g = _all_in_showdown([50, 100, 100], deck)
    r = g.result
    assert r["winners"] == [0, 1], r          # 两家都拿到钱
    assert r["tie"] is False, "边池由不同人赢下，不是平局"
    assert r["payouts"] == [150, 100, 0], r   # 主池 50×3 归 P0，边池 50×2 归 P1
    assert r["pot"] == 250 and sum(r["payouts"]) == 250
    assert [p["split"] for p in r["pots"]] == [False, False], r["pots"]
    assert r["ranks"] == {"0": "一对", "1": "一对", "2": "一对"}, r["ranks"]
    assert sum(g.stacks) == 250, f"筹码不守恒 {g.stacks}"
    print(f"  [ok] 边池分层 -> pots={r['pots']} payouts={r['payouts']}")


def test_odd_chip_tie_is_not_reported_as_even_split():
    """平局但底池是奇数：多出的 1 个筹码只能给一家，payouts 不能相等。

    构造：小盲/大盲都是 1，三家各 5。P0/P1 全下、P2（大盲）弃牌。
    第一层池 3（三家各出 1，只有 P0/P1 有资格）→ 2 + 1；第二层 8 → 各 4。
    """
    deck = ["2h", "3d", "4c", "5h", "6c", "7d"] + list(ROYAL)   # P0/P1 打公共牌平局
    g = Hand([5, 5, 5], button=0, sb=1, bb=1, deck=_deck(deck))
    while g.to_act is not None:
        i = g.to_act
        acts = g.legal_actions()
        if i == 0:
            a = next(x for x in acts if x.kind == "raise" and x.amount == 5)
        elif i == 1:
            a = next(x for x in acts if x.kind == "call")
        else:
            a = next(x for x in acts if x.kind == "fold")
        g.apply(a)
    r = g.result
    assert r["winners"] == [0, 1] and r["tie"] is True, r
    assert r["payouts"] == [6, 5, 0], r
    assert r["pot"] == 11 and sum(r["payouts"]) == 11
    assert r["pots"][0]["split"] is True and r["pots"][0]["amount"] == 3
    assert [w["amount"] for w in r["pots"][0]["winners"]] == [2, 1], r["pots"][0]
    assert sum(g.stacks) == 15, f"筹码不守恒 {g.stacks}"
    print(f"  [ok] 奇数底池平局 -> payouts={r['payouts']} pots={r['pots']}")


def test_fold_out_has_no_ranks_and_pays_whole_pot():
    """对手弃牌：不摊牌（showdown=False、ranks=None），整池归赢家。"""
    g = Hand([200, 200], button=0, deck=make_deck())
    g.apply(Action("raise", 6))
    g.apply(Action("fold"))
    r = g.result
    assert r["showdown"] is False and r["ranks"] is None
    assert r["winners"] == [0] and r["tie"] is False
    assert r["payouts"] == [8, 0] and r["pot"] == 8, r
    assert len(r["pots"]) == 1 and r["pots"][0]["winners"] == [{"seat": 0, "amount": 8}]
    assert g.stacks == [202, 198] and sum(g.stacks) == 400, g.stacks
    assert g.describe_result() == "P0 赢得 8", g.describe_result()
    print(f"  [ok] 弃牌收池 -> payouts={r['payouts']} describe={g.describe_result()!r}")


def test_random_hands_payouts_conserve_the_pot():
    """随机自搏（2/3/6 人）：payouts 必须恰好分完底池，且 winners == 拿到钱的人。"""
    rng = random.Random(20260)
    hands = 0
    for n in (2, 3, 6):
        for h in range(120):
            total = 200 * n
            g = Hand([200] * n, button=h % n, rng=rng)
            guard = 0
            while g.to_act is not None and guard < 400:
                g.apply(rng.choice(g.legal_actions()))
                guard += 1
            r = g.result
            assert sum(g.stacks) == total, f"筹码不守恒(n={n}) {g.stacks}"
            assert sum(r["payouts"]) == r["pot"] == sum(g.contrib), \
                f"payouts 没分完底池(n={n}): {r}"
            assert set(r["winners"]) == {i for i, v in enumerate(r["payouts"]) if v > 0}
            assert sum(p["amount"] for p in r["pots"]) == r["pot"], r["pots"]
            for p in r["pots"]:
                assert sum(w["amount"] for w in p["winners"]) == p["amount"], p
                assert p["split"] == (len(p["winners"]) > 1), p
            hands += 1
    print(f"  [ok] {hands} 手随机自搏: payouts 恰好分完底池 + 边池明细自洽")


if __name__ == "__main__":
    test_board_plays_tie_names_both_winners()
    test_side_pots_are_not_a_tie()
    test_odd_chip_tie_is_not_reported_as_even_split()
    test_fold_out_has_no_ranks_and_pays_whole_pot()
    test_random_hands_payouts_conserve_the_pot()
    print("RESULT DETAIL TESTS PASSED")
