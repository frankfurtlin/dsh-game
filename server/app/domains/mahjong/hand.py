"""手牌算法 —— **向听数 / 有效进张 / 胡牌判定**，这是训练器的核心价值。

德扑给的是胜率和底池赔率；麻将对应的"数学真相"是：
- **向听数 (shanten)**：离听牌还差几次换牌。0 = 听牌，-1 = 已胡。
- **有效进张 (ukeire)**：哪些牌能推进向听、牌墙里还剩几张。这直接回答"我该打哪张"。
- **放铳不算**（v1 不做危险牌提示，那是 `assist` 的后续项）。

算法：按门拆解 + 记忆化。每门枚举所有 (面子数, 搭子数, 是否有将) 组合，
再跨门合并取最优。27 个牌种、每张 ≤4 副的状态空间很小，`lru_cache` 一挂就够快；
德扑 equity 那次吃过"每迭代重建列表"的亏，所以这里一律走 27 长度计数数组 + 缓存。

定缺的处理：把缺门整门按"不能成面子"算（贡献恒为 0 面子 0 搭子 0 将），
但它占着手牌位、要被换掉 —— 标准公式 `8 - 2*面子 - 搭子` 本来就假定手牌是 13/14 张，
缺门牌当孤张处理正好等价于"每次摸打换掉一张"，所以结果是对的。
"""
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

from .tiles import (N_KINDS, SUITS, TILES_PER_KIND, Tile, suit_of, tile_at,
                    to_counts)

MAX_SHANTEN = 8
_TENPAI = 0
_WIN = -1

_EMPTY_SHAPES = frozenset({(0, 0, False)})


# ---------- 单门枚举 ----------
@lru_cache(maxsize=None)
def _shapes(c9: Tuple[int, ...]) -> frozenset:
    """枚举某门所有可达的 (面子数, 搭子数, 是否含将)。

    枚举项：刻子、顺子、将(对子)、搭子(对子/两面/嵌张)、以及"这张不要"。
    「这张不要」分支让同一个牌种可以少用几张，覆盖所有拆解方式。
    """
    out = set()
    c = list(c9)

    def rec(i: int, melds: int, part: int, pair: bool) -> None:
        while i < 9 and c[i] == 0:
            i += 1
        if i >= 9:
            out.add((melds, part, pair))
            return
        # 把这张当孤张（不要）
        c[i] -= 1
        rec(i, melds, part, pair)
        c[i] += 1
        # 刻子
        if c[i] >= 3:
            c[i] -= 3
            rec(i, melds + 1, part, pair)
            c[i] += 3
        # 顺子
        if i + 2 < 9 and c[i + 1] and c[i + 2]:
            c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
            rec(i, melds + 1, part, pair)
            c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
        # 将（只能有一个）
        if c[i] >= 2 and not pair:
            c[i] -= 2
            rec(i, melds, part, True)
            c[i] += 2
        # 搭子：对子
        if c[i] >= 2:
            c[i] -= 2
            rec(i, melds, part + 1, pair)
            c[i] += 2
        # 搭子：两面/边张
        if i + 1 < 9 and c[i + 1]:
            c[i] -= 1; c[i + 1] -= 1
            rec(i, melds, part + 1, pair)
            c[i] += 1; c[i + 1] += 1
        # 搭子：嵌张
        if i + 2 < 9 and c[i + 2]:
            c[i] -= 1; c[i + 2] -= 1
            rec(i, melds, part + 1, pair)
            c[i] += 1; c[i + 2] += 1

    rec(0, 0, 0, False)
    return frozenset(out)


def _chiitoi_pairs(counts: Sequence[int]) -> int:
    """七对的"对数" —— **4 张同牌算 2 对**。

    这是川麻和日麻的关键差别：日麻七对子要求 7 种**不同**的对子，
    4 张同牌只算一对；川麻的**龙七对**恰恰就是"七对里含一个暗杠"，
    所以这里必须 `n // 2`。写成 `n >= 2` 会把龙七对漏判成没胡。
    """
    return sum(n // 2 for n in counts)


def _shanten_chiitoi(counts: Sequence[int]) -> int:
    """七对向听 = 6 - 对数。

    13/14 张手牌下不需要日麻那条 `max(0, 7 - 牌种数)` 补偿：
    每种牌最多 4 张（最多供 2 对），而 13 张牌至少要 4 个牌种才装得下，
    所以"牌种不够"这种情况天然不会出现。
    """
    return 6 - _chiitoi_pairs(counts)


def shanten(counts: Sequence[int], open_melds: int = 0,
            void_suit: Optional[str] = None, chiitoi: bool = True) -> int:
    """向听数：-1 已胡，0 听牌，n 还差 n 次换牌。

    open_melds 是已经亮出的面子数（碰/杠各算 1 个面子）。
    void_suit 是定缺的那门 —— 整门按僵牌算，不参与成面子。
    七对只在「手牌全在有效两门内」时参与比较（还有缺门牌时它不成立，
    硬算会给出偏小的数，宁可不算）。
    """
    shapes = []
    for k, s in enumerate(SUITS):
        if s == void_suit:
            shapes.append(_EMPTY_SHAPES)
        else:
            shapes.append(_shapes(tuple(counts[k * 9:(k + 1) * 9])))

    best = MAX_SHANTEN
    for m1, p1, q1 in shapes[0]:
        for m2, p2, q2 in shapes[1]:
            for m3, p3, q3 in shapes[2]:
                m = m1 + m2 + m3 + open_melds
                if m > 4:
                    continue
                p = p1 + p2 + p3
                q = q1 or q2 or q3
                slots = 5 - m                      # 4 面子 + 1 将 = 5 组
                use_p = min(p, slots)
                d = use_p + (1 if (q and use_p < slots) else 0)
                st = 8 - 2 * m - d
                # 5 组都凑满了却没有将，就还得多换一步
                if m + d == 5 and not q:
                    st += 1
                if st < best:
                    best = st

    if chiitoi and open_melds == 0 and void_suit is not None:
        if all(counts[i] == 0 for i in range(N_KINDS) if suit_of(i) == void_suit):
            best = min(best, _shanten_chiitoi(counts))
    elif chiitoi and open_melds == 0:
        best = min(best, _shanten_chiitoi(counts))
    return best


def is_win(counts: Sequence[int], open_melds: int = 0,
           void_suit: Optional[str] = None) -> bool:
    """胡牌判定：4 面子 + 1 将，或七对。定缺未打完不算胡。"""
    if void_suit is not None:
        if any(counts[i] for i in range(N_KINDS) if suit_of(i) == void_suit):
            return False
    total = sum(counts) + 3 * open_melds
    if total != 14:
        return False
    if shanten(counts, open_melds, void_suit) == _WIN:
        return True
    return open_melds == 0 and _shanten_chiitoi(counts) == _WIN


# ---------- 有效进张 ----------
def ukeire(counts: Sequence[int], open_melds: int = 0,
           void_suit: Optional[str] = None,
           left: Optional[Sequence[int]] = None) -> Tuple[int, List[Dict]]:
    """现在这张手牌的有效进张。

    返回 (总枚数, [{tile, idx, count, shanten}...])。
    `left` 是每个牌种在牌墙里还剩几张（不传就按"4 - 自己手里的张数"估）。
    """
    cur = shanten(counts, open_melds, void_suit)
    if cur <= _WIN:
        return 0, []
    if left is None:
        left = [TILES_PER_KIND - n for n in counts]
    total = 0
    detail: List[Dict] = []
    for i in range(N_KINDS):
        if left[i] <= 0 or counts[i] >= TILES_PER_KIND:
            continue
        if void_suit is not None and suit_of(i) == void_suit:
            continue                       # 缺门牌永远不会推进向听
        nxt = list(counts)
        nxt[i] += 1
        st = shanten(nxt, open_melds, void_suit)
        if st < cur:
            total += left[i]
            detail.append({"tile": tile_at(i).code, "idx": i,
                           "count": left[i], "shanten": st})
    detail.sort(key=lambda d: d["idx"])
    return total, detail


# ---------- 打哪张 ----------
def legal_discards(counts: Sequence[int], void_suit: Optional[str] = None) -> List[int]:
    """可以打哪些牌（索引列表）。

    川麻**定缺**后必须先打完缺门牌 —— 手里还有缺门牌时不能打别门。
    """
    void = [i for i in range(N_KINDS) if suit_of(i) == void_suit and counts[i] > 0]
    if void:
        return void
    return [i for i in range(N_KINDS) if counts[i] > 0]


def discard_analysis(counts: Sequence[int], open_melds: int = 0,
                     void_suit: Optional[str] = None,
                     left: Optional[Sequence[int]] = None) -> List[Dict]:
    """每张可打的牌都试一遍，给出 (打掉后向听, 进张枚数, 进张明细)，按最优排序。

    这就是决策辅助面板的主体 —— 直接回答"我现在该打哪张、为什么"。
    排序：向听越小越好；同向听则进张越多越好；再同则打孤张（不破坏搭子）。
    """
    base_left = list(left) if left is not None else [TILES_PER_KIND - n for n in counts]
    rows: List[Dict] = []
    for d in legal_discards(counts, void_suit):
        nxt = list(counts)
        nxt[d] -= 1
        st = shanten(nxt, open_melds, void_suit)
        # 打掉的这张自己也算回到牌墙里可摸
        nxt_left = list(base_left)
        nxt_left[d] += 1
        n, detail = ukeire(nxt, open_melds, void_suit, left=nxt_left)
        rows.append({"discard": tile_at(d).code, "idx": d, "shanten": st,
                     "ukeire": n, "ukeire_detail": detail})
    rows.sort(key=lambda r: (r["shanten"], -r["ukeire"], r["idx"]))
    return rows


def best_discards(counts: Sequence[int], open_melds: int = 0,
                  void_suit: Optional[str] = None,
                  left: Optional[Sequence[int]] = None) -> List[Dict]:
    """并列最好的几张（同向听、同进张数）。"""
    rows = discard_analysis(counts, open_melds, void_suit, left)
    if not rows:
        return []
    top = rows[0]
    return [r for r in rows if r["shanten"] == top["shanten"] and r["ukeire"] == top["ukeire"]]


# ---------- 番型 ----------
def _can_all_triplets(counts: Sequence[int], need_melds: int) -> bool:
    """能否拆成 need_melds 个刻子 + 1 个将。"""
    def rec(c, i, melds, pair_used):
        while i < N_KINDS and c[i] == 0:
            i += 1
        if i >= N_KINDS:
            return melds == need_melds and pair_used
        if c[i] >= 3:
            c[i] -= 3
            if rec(c, i, melds + 1, pair_used):
                c[i] += 3
                return True
            c[i] += 3
        if c[i] >= 2 and not pair_used:
            c[i] -= 2
            ok = rec(c, i, melds, True)
            c[i] += 2
            if ok:
                return True
        return False
    return rec(list(counts), 0, 0, False)


def win_types(counts: Sequence[int], open_melds: int = 0,
              void_suit: Optional[str] = None,
              exposed_suits: Sequence[str] = ()) -> List[str]:
    """番型判定（简化）：平胡 / 对对胡 / 清一色 / 七对 / 龙七对 / 金钩钓。

    川麻不需要"役"就能胡，所以这些是**加番项**而不是胡牌门槛。
    """
    if not is_win(counts, open_melds, void_suit):
        return []
    out: List[str] = []
    kinds = [i for i in range(N_KINDS) if counts[i] > 0]
    suits = {suit_of(i) for i in kinds} | set(exposed_suits)
    if len(suits) == 1:
        out.append("清一色")
    if open_melds == 0:
        if _chiitoi_pairs(counts) == 7:
            out.append("龙七对" if any(n == 4 for n in counts) else "七对")
        elif _can_all_triplets(counts, 4):
            out.append("对对胡")
    else:
        if _can_all_triplets(counts, 4 - open_melds):
            out.append("对对胡")
        if open_melds == 4:
            out.append("金钩钓")
    if not out:
        out.append("平胡")
    return out


# ---------- 给前端看的汇总 ----------
def advise(counts: Sequence[int], open_melds: int = 0,
           void_suit: Optional[str] = None,
           left: Optional[Sequence[int]] = None) -> Dict:
    """决策辅助面板要的一整块数据。"""
    cur = shanten(counts, open_melds, void_suit)
    n, detail = ukeire(counts, open_melds, void_suit, left)
    # discard_analysis 只跑一次：best_discards 内部也是它，之前调两次白算了 13 ms
    rows = discard_analysis(counts, open_melds, void_suit, left)
    top = rows[0] if rows else None
    best = ([r["discard"] for r in rows
             if r["shanten"] == top["shanten"] and r["ukeire"] == top["ukeire"]]
            if top else [])
    return {
        "shanten": cur,
        "tenpai": cur == _TENPAI,
        "ukeire": n,
        "ukeire_detail": detail,
        "best_discards": best,
        "discards": rows,
    }
