"""evaluator 单元测试：已知牌型 + 交叉校验。"""
import itertools
import random
import sys

from .cards import Card, make_deck
from .evaluator import evaluate_five, evaluate_best, category_name, compare


def C(s):
    return [Card(x) for x in s.split()]


def test_known_categories():
    cases = {
        "As Ks Qs Js Ts 2h 3d": 8,
        "As 2s 3s 4s 5s 9h 9d": 8,
        "9s 9h 9d 9c 2s 3d 4h": 7,
        "9s 9h 9d 2c 2s 3d 4h": 6,
        "As Ks Qs Js 9s 2h 3d": 5,
        "9s 8h 7d 6c 5s 2h 3d": 4,
        "9s 9h 9d 2c 5s 3d 4h": 3,
        "9s 9h 2d 2c 5s 3d 4h": 2,
        "9s 9h 8d 2c 5s 3d 4h": 1,
        "9s 8h 7d 2c 5s 3d 4h": 0,
    }
    for hand, want in cases.items():
        got = evaluate_best(C(hand))[0]
        assert got == want, f"{hand}: got {category_name(evaluate_best(C(hand)))}, want {want}"
    print("  [ok] known categories")


def test_ordering():
    # 高牌点数比较
    assert compare(evaluate_best(C("As Kh 9d 7c 5s 3d 2h")),
                   evaluate_best(C("As Qh 9d 7c 5s 3d 2h"))) == 1
    # 踢脚比较
    assert compare(evaluate_best(C("Ks Kh Ad 7c 5s 3d 2h")),
                   evaluate_best(C("Ks Kh Qd 7c 5s 3d 2h"))) == 1
    # 轮子顺子 < 6 高顺子
    assert compare(evaluate_best(C("As 2h 3d 4c 5s Kd Qh")),
                   evaluate_best(C("2s 3h 4d 5c 6s Kd Qh"))) == -1
    # 同花 vs 顺子：同花更大
    assert compare(evaluate_best(C("As Ks Qs Js 9s 2h 3d")),
                   evaluate_best(C("9s 8h 7d 6c 5s 2h 3d"))) == 1
    # 完全相同牌力（同点不同花色）= 平局
    assert compare(evaluate_best(C("As Kh 9d 7c 5s 3d 2h")),
                   evaluate_best(C("Ah Kd 9s 7d 5h 3c 2s"))) == 0
    print("  [ok] ordering")


def brute_force_best(seven):
    """独立参考实现：按 (category, tiebreak) 纯暴力比较。"""
    def key(cards):
        ranks = sorted((c.rv for c in cards), reverse=True)
        suits = [c.suit for c in cards]
        flush = len(set(suits)) == 1
        uniq = sorted(set(ranks))
        straight_high = None
        if len(uniq) == 5:
            if uniq[-1] - uniq[0] == 4:
                straight_high = uniq[-1]
            elif uniq == [2, 3, 4, 5, 14]:
                straight_high = 5
        from collections import Counter
        cnt = Counter(ranks)
        rep = sorted(cnt.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
        cc = [g[1] for g in rep]
        if straight_high and flush:
            return (8, straight_high)
        if cc[0] == 4:
            return (7, rep[0][0], rep[1][0])
        if cc[0] == 3 and cc[1] == 2:
            return (6, rep[0][0], rep[1][0])
        if flush:
            return (5,) + tuple(ranks)
        if straight_high:
            return (4, straight_high)
        if cc[0] == 3:
            return (3, rep[0][0]) + tuple(sorted((g[0] for g in rep[1:]), reverse=True))
        if cc[0] == 2 and cc[1] == 2:
            pr = sorted((g[0] for g in rep[:2]), reverse=True)
            return (2,) + tuple(pr) + (rep[2][0],)
        if cc[0] == 2:
            return (1, rep[0][0]) + tuple(sorted((g[0] for g in rep[1:]), reverse=True))
        return (0,) + tuple(ranks)

    return max(key(list(c)) for c in itertools.combinations(seven, 5))


def test_cross_check():
    rng = random.Random(12345)
    deck = make_deck()
    for _ in range(3000):
        seven = rng.sample(deck, 7)
        assert evaluate_best(seven) == brute_force_best(seven), seven
    print("  [ok] cross-check 3000 random 7-card hands")


def test_exhaustive_5card_consistent():
    """枚举全部 5 张组合，evaluate_five 与参考 key 一致。"""
    deck = make_deck()
    rng = random.Random(7)
    sample = rng.sample(list(itertools.combinations(deck, 5)), 5000)
    for combo in sample:
        combo = list(combo)
        assert evaluate_five(combo) == brute_force_best(combo), combo
    print("  [ok] exhaustive-ish 5000 five-card combos consistent")


if __name__ == "__main__":
    test_known_categories()
    test_ordering()
    test_cross_check()
    test_exhaustive_5card_consistent()
    print("ALL EVALUATOR TESTS PASSED")
