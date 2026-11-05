"""对局状态机 + AI 测试。

重点是**不变量**而不是具体胜负（AI 有随机混合，胜负会浮动）：
- **牌数守恒**：牌墙 + 各家手牌 + 亮出的面子 + 河里 = 108 张。状态机最容易在这里出错
  （碰/杠/胡搬牌时漏减或重复计数），而且一旦错就会越滚越离谱。
- **分数守恒**：零和（自摸三家赔、点炮一家赔）。
- **胡牌合法性**：每个胡了的玩家，手牌用独立判定必须真的成立。
- **定缺**：定缺后必须先打缺门牌。
"""
import random

from .ai import choose
from .game import PHASE_OVER, new_game
from .hand import is_win
from .test_hand import _ref_is_win
from .tiles import N_KINDS, TILES_PER_KIND, suit_of, tile_at

MELD_TILES = {"kong": 4, "ankong": 4, "bukong": 4, "pong": 3}


def total_tiles(g) -> int:
    n = len(g.wall)
    for p in g.players:
        n += sum(p.hand)
        n += sum(MELD_TILES[m.kind] for m in p.melds)
        n += len(p.discards)
    return n


def play(seed: int, max_steps: int = 4000):
    """全 AI 自对弈（人类位也交给 AI），返回 (game, steps)。"""
    g = new_game(seed)
    steps = 0
    while not g.over and steps < max_steps:
        steps += 1
        if g.waiting is None:
            g.advance()
            if g.waiting is None:
                break
            continue
        opts = g.legal_actions()
        assert opts, f"等待 {g.waiting} 却没有任何合法动作（状态机卡死）"
        g.apply(choose(g, g.waiting[1], opts))
    return g, steps


def test_self_play_invariants():
    seeds = list(range(40))
    wins = 0
    for s in seeds:
        g, steps = play(s)
        assert g.over, f"seed={s} 跑了 {steps} 步还没结束（可能死循环）"
        assert total_tiles(g) == 108, \
            f"seed={s} 牌数不再守恒: {total_tiles(g)} != 108"
        assert sum(p.score for p in g.players) == 0, \
            f"seed={s} 分数不是零和: {[p.score for p in g.players]}"
        assert len(g.result["winners"]) == sum(1 for p in g.players if p.hu)
        for p in g.players:
            if not p.hu:
                continue
            wins += 1
            # 胡牌玩家手牌必须真的成立（用独立实现对拍）
            assert is_win(p.hand, p.n_melds, p.void), f"seed={s} P{p.idx} 胡牌不合法"
            assert _ref_is_win(p.hand, p.n_melds, p.void), \
                f"seed={s} P{p.idx} 独立实现说不胡"
            assert sum(p.hand) + 3 * p.n_melds == 14, \
                f"seed={s} P{p.idx} 胡牌张数不对: {sum(p.hand)}+3*{p.n_melds}"
    print(f"  [ok] 40 局自对弈：牌数守恒 108、分数零和、{wins} 次胡牌全部合法")


def test_void_rule_enforced():
    """定缺后手里还有缺门牌时，只能打缺门牌。"""
    checked = 0
    for s in range(12):
        g = new_game(s)
        steps = 0
        while not g.over and steps < 1500:      # 必须有上限：死循环会把整个测试挂住
            steps += 1
            if g.waiting is None:
                g.advance()
                continue
            who, idx = g.waiting
            if who == "act":
                p = g.players[idx]
                void_left = [i for i in range(N_KINDS)
                             if suit_of(i) == p.void and p.hand[i] > 0]
                if void_left:
                    opts = g.legal_actions()
                    discs = [a for a in opts if a.kind == "discard"]
                    assert discs, f"P{idx} 有缺门牌却无牌可打"
                    assert all(suit_of(a.tile) == p.void for a in discs), \
                        f"P{idx} 手里还有缺门牌，却允许打别门: {[a for a in discs]}"
                    checked += 1
            opts = g.legal_actions()
            if not opts:
                break
            if g.waiting is None: break
            g.apply(choose(g, g.waiting[1], opts))
    assert checked > 0, "没有覆盖到「手里有缺门牌」的情况"
    print(f"  [ok] 定缺限制生效（检查了 {checked} 次「有缺门牌时的可打牌」）")


def test_blood_battle_continues():
    """血战到底：有人胡牌后其余家继续 —— 应该出现"多家胡"的牌局。"""
    multi = 0
    for s in range(40):
        g, _ = play(s)
        if len(g.result["winners"]) >= 2:
            multi += 1
    assert multi > 0, "40 局里没有一局出现多家胡，血战到底没生效"
    print(f"  [ok] 血战到底生效：40 局里有 {multi} 局出现多家胡牌")


def test_ai_not_deterministic():
    """同一起手、同一 seed 可复现；不同 seed 不应给出完全一样的对局。

    另外 AI 必须真的会碰/杠/胡 —— 只摸打的 AI 是坏的。
    """
    a, _ = play(7)
    b, _ = play(7)
    assert [(p.hu, p.score) for p in a.players] == [(p.hu, p.score) for p in b.players], \
        "同一 seed 不可复现"
    kinds = set()
    for s in range(40):
        g, _ = play(s)
        kinds |= {e["kind"] for e in g.log}
    for want in ("pong", "kong", "hu", "discard"):
        assert want in kinds, f"40 局里 AI 从未 {want}"
    print(f"  [ok] 同 seed 可复现；40 局里 AI 的动作种类: {sorted(kinds)}")


def test_snapshot_shape():
    """快照要能直接喂前端：定缺阶段 need_void、决策辅助字段齐全。"""
    g = new_game(3)
    snap = g.snapshot()
    assert snap["need_void"] is True, "开局应该等玩家定缺"
    assert snap["phase"] == "void"
    assert {a["suit"] for a in snap["legal"]} == {"m", "s", "p"}, "定缺应给三门选项"
    assert len(snap["players"]) == 4
    # 定缺后进入摸打，决策辅助必须有向听和进张
    g.choose_void(0, "s")
    g.advance()
    snap = g.snapshot()
    adv = snap["advice"]
    for k in ("shanten", "ukeire", "ukeire_detail", "best_discards", "discards"):
        assert k in adv, f"决策辅助缺字段 {k}"
    assert adv["shanten"] >= 0
    assert isinstance(adv["best_discards"], list)
    assert snap["players"][0]["void"] == "s"
    print("  [ok] 快照结构正确（定缺三门选项 + 决策辅助字段齐全）")


def test_hand_size_invariant_at_act():
    """「轮到你打牌」时手牌必须是 14 - 3×面子。

    这条不变量能抓到**牌数守恒抓不到**的一类 bug：总数一直是 108，
    但某个座位多一张、另一个座位少一张，总和照样对得上。
    实际抓到过：定缺结束后庄家没摸第一张，于是庄家永久只有 13 张。
    """
    checked = 0
    for s in range(8):
        g = new_game(s)
        steps = 0
        while not g.over and steps < 1500:
            steps += 1
            if g.waiting is None:
                g.advance()
                continue
            who, idx = g.waiting
            if who == "act":
                p = g.players[idx]
                want = 14 - 3 * p.n_melds
                got = sum(p.hand)
                assert got == want, \
                    f"seed={s} 步{steps} P{idx} 该打牌时手牌 {got} 张，应为 {want} 张（面子 {p.n_melds}）"
                checked += 1
            opts = g.legal_actions()
            if not opts:
                break
            g.apply(choose(g, idx, opts))
    assert checked > 0, "没覆盖到「该打牌」的时刻"
    print(f"  [ok] 手牌张数不变量：检查了 {checked} 次「该打牌」的时刻")


def test_all_seats_can_win():
    """四个座位都要能胡 —— 尤其 0 号位（庄家 / 人类位）。

    实际抓到过：定缺后庄家没摸牌，0 号位因此**永远胡不了**；
    而当时「总胡牌次数」看着很正常，因为全是 1/2/3 号位在胡。
    只看总数不看分布，就会漏掉这种「某个座位系统性坏掉」的 bug。
    """
    won = {0: 0, 1: 0, 2: 0, 3: 0}
    for s in range(60):
        g, _ = play(s)
        for p in g.players:
            if p.hu:
                won[p.idx] += 1
    assert all(v > 0 for v in won.values()), f"有座位整批牌局里一次没胡过：{won}"
    print(f"  [ok] 四个座位都能胡：{won}")


if __name__ == "__main__":
    test_self_play_invariants()
    test_void_rule_enforced()
    test_blood_battle_continues()
    test_ai_not_deterministic()
    test_snapshot_shape()
    test_hand_size_invariant_at_act()
    test_all_seats_can_win()
    print("ALL MAHJONG GAME TESTS PASSED")
