"""手牌算法测试 —— 向听数 / 进张 / 胡牌判定。

重点是**对拍**：`hand.py` 里向听数走的是"按门枚举 + 跨门合并"的快速公式，
这里另写一份直白的递归拆解 `_ref_is_win` 当参考实现，两条互不相干的代码路径
互相验证。只测"自己等于自己"的测试会一起错。

川麻特征也要覆盖：定缺（缺门牌必须优先打、胡牌时手里不能有缺门牌）、龙七对。
"""
import random

from .hand import (_chiitoi_pairs, discard_analysis, is_win, legal_discards,
                   shanten, ukeire, win_types)
from .tiles import (CN_NUMBERS, N_KINDS, SUIT_NAMES, make_wall, parse, parse_many,
                    rank_of, suit_of, tile_at, to_counts)


# ---------- 独立参考实现（慢，但直白） ----------
def _ref_win_shape(c, i, melds, pair, need):
    """递归把牌拆成 need 个面子 + 1 个将。"""
    while i < N_KINDS and c[i] == 0:
        i += 1
    if i >= N_KINDS:
        return melds == need and pair
    if c[i] >= 3:                                   # 刻子
        c[i] -= 3
        ok = _ref_win_shape(c, i, melds + 1, pair, need)
        c[i] += 3
        if ok:
            return True
    if rank_of(i) <= 7 and c[i + 1] and c[i + 2]:   # 顺子（同门连续）
        c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
        ok = _ref_win_shape(c, i, melds + 1, pair, need)
        c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
        if ok:
            return True
    if c[i] >= 2 and not pair:                      # 将
        c[i] -= 2
        ok = _ref_win_shape(c, i, melds, True, need)
        c[i] += 2
        if ok:
            return True
    c[i] -= 1                                       # 这张不参与组成
    ok = _ref_win_shape(c, i, melds, pair, need)
    c[i] += 1
    return ok


def _ref_is_win(counts, open_melds=0, void_suit=None):
    if void_suit is not None and any(counts[i] for i in range(N_KINDS)
                                     if suit_of(i) == void_suit):
        return False
    if sum(counts) + 3 * open_melds != 14:
        return False
    if open_melds <= 4 and _ref_win_shape(list(counts), 0, 0, False, 4 - open_melds):
        return True
    return open_melds == 0 and _chiitoi_pairs(counts) == 7


def _random_counts(n, rng):
    wall = make_wall()
    rng.shuffle(wall)
    return to_counts(wall[:n])


def _make_win_counts(rng):
    """**构造**一个必胡的手牌（4 面子 + 1 将，每张 ≤4）。

    不能靠随机抽 14 张去碰胡牌 —— 概率太低，实测 3000 手一个都没有，
    断言会静默地什么都不测。
    """
    while True:
        c = [0] * N_KINDS
        for _ in range(4):
            if rng.random() < 0.5:                       # 刻子
                c[rng.randrange(N_KINDS)] += 3
            else:                                        # 顺子
                base = rng.randrange(3) * 9 + rng.randrange(1, 8) - 1
                c[base] += 1; c[base + 1] += 1; c[base + 2] += 1
        c[rng.randrange(N_KINDS)] += 2                   # 将
        if all(n <= 4 for n in c):
            return c


def _make_chiitoi_counts(rng):
    """构造七对手牌（7 个不同牌种各 2 张）。"""
    kinds = rng.sample(range(N_KINDS), 7)
    c = [0] * N_KINDS
    for i in kinds:
        c[i] = 2
    return c


# ---------- 1. 已知牌例 ----------
def test_known_shanten():
    cases = [
        ("123m456m789m123s99p", 14, -1, "4 面子 + 1 将，已胡"),
        ("123m456m789m123s9p", 13, 0, "4 面子 + 单张，听 9p"),
        ("123m456m789m12s99p", 13, 0, "3 面子 + 搭子 + 将，听 3s"),
        ("123m456m789m12s95p", 13, 1, "3 面子 + 搭子，无将"),
        ("123m456m789m1s4s7s9p", 13, 2, "3 面子 + 4 张全孤张"),
        ("1112345678999m", 13, 0, "九莲宝灯：单色 13 张听全 9 面"),
        ("1122334455667m", 13, 0, "六对 + 单张，七对听牌（也是 4 面子型）"),
        ("1111m22m33m44m55m66m", 14, -1, "龙七对：4 张同牌算 2 对"),
        ("11m22m33m44m55m66m77m", 14, -1, "普通七对"),
        ("111m222m333m444m55m", 14, -1, "对对胡（单色）"),
    ]
    for code, n, want, why in cases:
        counts = to_counts(parse_many(code))
        assert sum(counts) == n, f"{code}: 张数算错 {sum(counts)} != {n}"
        got = shanten(counts)
        assert got == want, f"{code}（{why}）向听 {got} != {want}"
    print("  [ok] 10 个已知牌例向听数全部正确")


def test_win_types():
    cases = [
        ("123m456m789m123s99p", 0, ["平胡"]),
        ("111m222m333m444m55m", 0, ["清一色", "对对胡"]),
        # 全是一门，所以"清一色"和牌型番是叠加的（川麻没有"役"门槛）
        ("11m22m33m44m55m66m77m", 0, ["清一色", "七对"]),
        ("1111m22m33m44m55m66m", 0, ["清一色", "龙七对"]),
        ("123m456m789m123s99s", 0, ["平胡"]),
    ]
    for code, om, want in cases:
        got = win_types(to_counts(parse_many(code)), om)
        assert got == want, f"{code}: 番型 {got} != {want}"
    # 金钩钓：4 个面子全亮出，手里只剩将
    got = win_types(to_counts(parse_many("99p")), 4)
    assert "金钩钓" in got, f"金钩钓漏判: {got}"
    print("  [ok] 番型判定：平胡/清一色/对对胡/七对/龙七对/金钩钓")


# ---------- 2. 与独立参考实现对拍 ----------
def test_is_win_matches_reference():
    rng = random.Random(20261006)
    for _ in range(400):
        n = rng.choice([13, 14])
        counts = _random_counts(n, rng)
        assert is_win(counts) == _ref_is_win(counts), f"胡牌判定不一致: {counts}"
        # 带定缺也对拍一次
        v = rng.choice(["m", "s", "p"])
        assert is_win(counts, 0, v) == _ref_is_win(counts, 0, v), \
            f"定缺({v})胡牌判定不一致: {counts}"
    # 副露（碰/杠）也对拍
    for _ in range(150):
        om = rng.randint(1, 3)
        counts = _random_counts(14 - 3 * om, rng)
        assert is_win(counts, om) == _ref_is_win(counts, om), \
            f"副露 {om} 个胡牌判定不一致: {counts}"
    print("  [ok] 550 个随机手牌：胡牌判定与独立参考实现一致")


def test_tenpai_equals_exists_winning_draw():
    """听牌的定义就是"摸到某张就能胡" —— 用它反过来验向听数公式。"""
    rng = random.Random(31415)
    checked = 0
    for _ in range(220):
        counts = _random_counts(13, rng)
        st = shanten(counts)
        has_winning_draw = False
        for i in range(N_KINDS):
            if counts[i] >= 4:
                continue
            c = list(counts)
            c[i] += 1
            if _ref_is_win(c):
                has_winning_draw = True
                break
        assert (st == 0) == has_winning_draw, (
            f"向听={st} 与「是否存在胡牌张」={has_winning_draw} 矛盾: {counts}")
        checked += 1
    print(f"  [ok] {checked} 个随机 13 张手牌：向听 0 ⇔ 存在胡牌张")


def test_shanten_bounds_and_monotonic():
    """结构不变量：13 张向听 ≥0；胡了的手牌去掉任一张应该 ≤0 向听。"""
    rng = random.Random(2718)
    for _ in range(300):
        counts = _random_counts(13, rng)
        st = shanten(counts)
        assert 0 <= st <= 8, f"13 张手牌向听越界: {st} {counts}"

    # 胡牌手牌用**构造**的，保证真的覆盖到
    checked = 0
    for _ in range(400):
        counts = _make_win_counts(rng) if rng.random() < 0.7 else _make_chiitoi_counts(rng)
        assert _ref_is_win(counts), f"构造出来的手牌竟然不胡: {counts}"
        assert shanten(counts) == -1, f"已胡的手牌向听不是 -1: {counts}"
        for i in range(N_KINDS):
            if counts[i] == 0:
                continue
            c = list(counts)
            c[i] -= 1
            st = shanten(c)
            assert st <= 0, f"从胡牌手牌去掉 {tile_at(i)} 后向听 {st} > 0: {counts}"
            checked += 1
    print(f"  [ok] 向听数边界正确；构造的 400 个胡牌手牌共去掉 {checked} 张，向听都 ≤ 听牌")


# ---------- 3. 定缺 ----------
def test_void_suit():
    counts = to_counts(parse_many("123m456m789m99p 123s"))
    assert sum(counts) == 14
    assert is_win(counts) is True, "无缺门时应该能胡"
    # 定缺条子：手里有 123s 就不能胡
    assert is_win(counts, 0, "s") is False, "手里还有缺门牌时不能胡"
    # 缺门牌必须优先打（只列手里真有的那几张缺门牌）
    assert sorted(legal_discards(counts, "s")) == sorted(
        [i for i in range(N_KINDS) if suit_of(i) == "s" and counts[i] > 0]
    ), "定缺后应该只能打缺门牌"
    # 打完缺门牌后恢复自由：手里没有缺门牌时不该再只推荐缺门
    clean = to_counts(parse_many("123m456m789m99p"))
    assert all(suit_of(i) != "s" for i in legal_discards(clean, "s")), \
        "手里没有缺门牌时不该推荐打缺门"
    assert len(legal_discards(clean, "s")) == 10, "1-9m + 9p 共 10 个牌种可打"
    # 缺门牌不参与进张
    _, detail = ukeire(to_counts(parse_many("123m456m789m12s95p")), 0, "p")
    assert all(suit_of(d["idx"]) != "p" for d in detail), "缺门的牌不该算进张"
    print("  [ok] 定缺：缺门牌必须优先打、不参与进张、手里有缺门牌时不能胡")


# ---------- 4. 进张与"打哪张" ----------
def test_ukeire_and_discard_analysis():
    # 听牌：123m456m789m12s99p 听 3s（剩余 4 张）
    counts = to_counts(parse_many("123m456m789m12s99p"))
    assert shanten(counts) == 0
    n, detail = ukeire(counts)
    assert n == 4, f"应该听 4 张 3s，实际 {n}：{detail}"
    assert [d["tile"] for d in detail] == ["3s"]

    # 打哪张：孤张应该被排在最前
    counts = to_counts(parse_many("123m456m789m12s9p5p"))
    rows = discard_analysis(counts)
    assert rows[0]["shanten"] == 1, f"最优打法应向听 1，实际 {rows[0]}"
    assert rows[0]["discard"] in ("5p", "9p"), f"应该打孤张，实际 {rows[0]}"
    # 排序单调：向听不增、同向听进张不减
    for a, b in zip(rows, rows[1:]):
        assert (a["shanten"], -a["ukeire"]) <= (b["shanten"], -b["ukeire"]), \
            f"排序不对: {a} {b}"

    # 随机手牌：最优打的向听必须等于所有打法里的最小值
    rng = random.Random(99)
    for _ in range(60):
        c = _random_counts(14, rng)
        rows = discard_analysis(c)
        if not rows:
            continue
        assert rows[0]["shanten"] == min(r["shanten"] for r in rows), "没取到最小向听"
    print("  [ok] 进张枚数正确、打哪张排序单调且取最小向听")


if __name__ == "__main__":
    test_known_shanten()
    test_win_types()
    test_is_win_matches_reference()
    test_tenpai_equals_exists_winning_draw()
    test_shanten_bounds_and_monotonic()
    test_void_suit()
    test_ukeire_and_discard_analysis()
    print("ALL MAHJONG HAND TESTS PASSED")


def test_tile_reading_is_chinese():
    """牌面读数必须是汉字（`3m` → `三万`）。

    `Tile.name` 是**给人看的**，出牌记录、碰/杠按钮、牌的悬停提示直接显示它；
    `Tile.code`（`3m`）才是接口/牌墙/进张用的紧凑编码。
    牌桌上说「碰三万」，没人说「碰 3m」—— 第一版就是直接显示 code，
    按钮上写着「碰 4m」，完全没法看。
    """
    assert tile_at(0).code == "1m" and tile_at(0).name == "一万"
    assert tile_at(8).code == "9m" and tile_at(8).name == "九万"
    assert tile_at(9).name == "一条" and tile_at(17).name == "九条"
    assert tile_at(18).name == "一筒" and tile_at(26).name == "九筒"
    for i in range(N_KINDS):
        t = tile_at(i)
        assert t.name == CN_NUMBERS[t.rank] + SUIT_NAMES[t.suit], t
        assert t.name[0] in "一二三四五六七八九", t.name
        assert t.name[-1] in "万条筒", t.name
        assert parse(t.code) == t, f"{t.code} 无法往返解析"
        # 读数里不该再出现阿拉伯数字或拉丁编码
        assert not any(ch.isdigit() or ch.isascii() for ch in t.name), t.name
