"""德州扑克手牌评估器：从 7 张牌取最佳 5 张，返回可比较的 rank 元组。
category: 0 高牌 / 1 一对 / 2 两对 / 3 三条 / 4 顺子 / 5 同花 /
         6 葫芦 / 7 四条 / 8 同花顺。
每条 rank 与同样 category 的牌可比，高者胜（元组字典序）。"""
import itertools
from collections import Counter
from typing import List, Tuple

from .cards import Card

# 返回类型别名
HandRank = Tuple[int, ...]


def evaluate_five(cards: List[Card]) -> HandRank:
    ranks = sorted((c.rv for c in cards), reverse=True)
    suits = [c.suit for c in cards]
    is_flush = len(set(suits)) == 1

    uniq = sorted(set(ranks))
    is_straight = False
    straight_high = None
    if len(uniq) == 5:
        if uniq[-1] - uniq[0] == 4:
            is_straight = True
            straight_high = uniq[-1]
        elif uniq == [2, 3, 4, 5, 14]:   # 轮子 A-2-3-4-5
            is_straight = True
            straight_high = 5

    cnt = Counter(ranks)
    # (点数, 张数) 先按张数降序再按点数降序
    groups = sorted(cnt.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    counts = [g[1] for g in groups]

    if is_straight and is_flush:
        return (8, straight_high)
    if counts[0] == 4:                          # 四条
        return (7, groups[0][0], groups[1][0])
    if counts[0] == 3 and counts[1] == 2:       # 葫芦
        return (6, groups[0][0], groups[1][0])
    if is_flush:                                # 同花
        return (5,) + tuple(ranks)
    if is_straight:                             # 顺子
        return (4, straight_high)
    if counts[0] == 3:                          # 三条
        return (3, groups[0][0]) + tuple(sorted((g[0] for g in groups[1:]), reverse=True))
    if counts[0] == 2 and counts[1] == 2:       # 两对
        pairs = sorted((g[0] for g in groups[:2]), reverse=True)
        return (2,) + tuple(pairs) + (groups[2][0],)
    if counts[0] == 2:                          # 一对
        pair = groups[0][0]
        return (1, pair) + tuple(sorted((g[0] for g in groups[1:]), reverse=True))
    return (0,) + tuple(ranks)                  # 高牌


def evaluate_best(seven: List[Card]) -> HandRank:
    """7 张取最佳 5 张。生产用快速位运算实现(见 evaluate_seven)。"""
    return evaluate_seven(seven)


# ---------- 快速 7 张评估器 (位运算, O(1) 组合, 供 equity 高频调用) ----------
_SUIT_IDX = {s: i for i, s in enumerate("shdc")}


def _straight_high(mask: int):
    """给定点数位掩码, 返回最大顺子高张(含 A-2-3-4-5 轮子), 无则 None。"""
    m = mask
    if m & (1 << 14):          # A 也可当 1
        m |= 1 << 1
    run = 0
    high = None
    for r in range(1, 15):
        if m & (1 << r):
            run += 1
            if run >= 5:
                high = r
        else:
            run = 0
    return high


def _top_ranks(mask: int, n: int):
    out = []
    for r in range(14, 1, -1):
        if mask & (1 << r):
            out.append(r)
            if len(out) == n:
                break
    return out


def _top_ranks_excl(mask: int, exclude: int, n: int):
    out = []
    for r in range(14, 1, -1):
        if (mask & (1 << r)) and r != exclude:
            out.append(r)
            if len(out) == n:
                break
    return out


def evaluate_seven(cards: List[Card]) -> HandRank:
    counts = [0] * 15
    smask = [0, 0, 0, 0]
    scount = [0, 0, 0, 0]
    rmask = 0
    for c in cards:
        r = c.rv
        s = _SUIT_IDX[c.suit]
        counts[r] += 1
        smask[s] |= (1 << r)
        scount[s] += 1
        rmask |= (1 << r)

    flush_suit = -1
    for s in range(4):
        if scount[s] >= 5:
            flush_suit = s
            break
    if flush_suit >= 0:
        sf = _straight_high(smask[flush_suit])
        if sf:                                  # 同花顺 (最高)
            return (8, sf)

    groups = [(counts[r], r) for r in range(14, 1, -1) if counts[r]]
    groups.sort(key=lambda x: (-x[0], -x[1]))
    g0 = groups[0]

    if g0[0] == 4:                              # 四条
        kicker = next((r for r in range(14, 1, -1)
                       if counts[r] and r != g0[1]), 0)
        return (7, g0[1], kicker)
    if g0[0] == 3 and len(groups) > 1 and groups[1][0] >= 2:   # 葫芦
        return (6, g0[1], groups[1][1])
    if flush_suit >= 0:                         # 同花
        return (5,) + tuple(_top_ranks(smask[flush_suit], 5))
    sh = _straight_high(rmask)
    if sh:                                      # 顺子
        return (4, sh)
    if g0[0] == 3:                              # 三条
        kickers = _top_ranks_excl(rmask, g0[1], 2)
        return (3, g0[1]) + tuple(kickers)
    if g0[0] == 2 and len(groups) > 1 and groups[1][0] == 2:   # 两对
        used = {g0[1], groups[1][1]}
        kicker = next((r for r in range(14, 1, -1)
                       if counts[r] and r not in used), 0)
        pr = sorted([g0[1], groups[1][1]], reverse=True)
        return (2, pr[0], pr[1], kicker)
    if g0[0] == 2:                              # 一对
        return (1, g0[1]) + tuple(_top_ranks_excl(rmask, g0[1], 3))
    return (0,) + tuple(_top_ranks(rmask, 5))   # 高牌


def category_name(rank: HandRank) -> str:
    names = ["高牌", "一对", "两对", "三条", "顺子", "同花",
             "葫芦", "四条", "同花顺"]
    return names[rank[0]]


def compare(a: HandRank, b: HandRank) -> int:
    """a > b 返回 1，相等 0，a < b 返回 -1。"""
    if a > b:
        return 1
    if a < b:
        return -1
    return 0


if __name__ == "__main__":
    def C(s):
        return [Card(x) for x in s.split()]
    # 同花顺
    print("royal:", evaluate_best(C("As Ks Qs Js Ts 2h 3d")))
    # 轮子同花顺
    print("wheel SF:", evaluate_best(C("As 2s 3s 4s 5s 9h 9d")))
    # 四条
    print("quads:", evaluate_best(C("9s 9h 9d 9c 2s 3d 4h")))
    # 葫芦
    print("boat:", evaluate_best(C("9s 9h 9d 2c 2s 3d 4h")))
    # 两对 vs 一对
    print("two pair > pair:", compare(evaluate_best(C("Ks Kh 2c 2d 9s 3d 4h")),
                                      evaluate_best(C("Ks Kh 5c 8d 9s 3d 4h"))))
