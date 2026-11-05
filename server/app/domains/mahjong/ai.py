"""AI 对手 —— 用 **向听数 + 有效进张** 驱动（也就是决策辅助面板用的同一套数学）。

和德扑 AI 一样刻意**不做成纯确定性**：如果 AI 每次都打数学最优的那张，
玩家看两圈就能学会它的出牌习惯；所以同向听、同进张的并列牌之间随机选，
另外留了一小部分概率打次优（牺牲一点强度换不可预测）。

取舍上：
- 能胡就胡（川麻没有"不胡等自摸"的理由，自摸已经 ×2 了）。
- 碰/杠只在**不让向听变差**时才做（碰完还要打一张，所以按碰后的向听比较）。
- 打牌一律从 `discard_analysis` 的最优里挑。
"""
import random
from typing import List, Optional

from .game import Action
from .hand import discard_analysis, shanten
from .tiles import N_KINDS, SUITS, suit_of

# 打次优牌的概率（换一点强度，换不被读死）
BLUNDER = 0.10
# 并列最优时随机选；同向听但进张略少时的容忍
PONG_BASE = 0.55


def choose(game, idx: int, options: List[Action],
           rng: Optional[random.Random] = None) -> Action:
    """给 idx 号玩家选一个动作。`options` 来自 `game.legal_actions()`。"""
    rng = rng or game.rng
    if not options:
        return Action("pass")
    kinds = {a.kind for a in options}

    if "void" in kinds:                                  # 定缺
        return _choose_void(game, idx, [a for a in options if a.kind == "void"], rng)
    if "hu" in kinds:
        return Action("hu")                              # 能胡就胡

    p = game.players[idx]
    kong = _maybe_kong(game, p, [a for a in options if a.kind == "kong"], rng)
    if kong is not None:
        return kong
    pong = _maybe_pong(game, p, [a for a in options if a.kind == "pong"], rng)
    if pong is not None:
        return pong

    discs = [a for a in options if a.kind == "discard"]
    if discs:
        return _choose_discard(game, p, discs, rng)
    return Action("pass")


def _choose_void(game, idx, voids, rng) -> Action:
    """定缺哪门：手里张数最少的那门（并列随机）。"""
    p = game.players[idx]
    counts = {s: sum(p.hand[i] for i in range(N_KINDS) if suit_of(i) == s)
              for s in SUITS}
    fewest = min(counts.values())
    best = [a for a in voids if counts[a.suit] == fewest]
    return rng.choice(best)


def _maybe_kong(game, p, kongs, rng) -> Optional[Action]:
    """杠：手牌少 3 张、面子多 1 个，向听不退化就杠（还能多摸一张）。"""
    if not kongs:
        return None
    cur = shanten(p.hand, p.n_melds, p.void)
    for a in kongs:
        c = list(p.hand)
        n = c[a.tile]
        if n >= 3:                       # 暗杠(4 张) / 明杠(3 张)：面子 +1
            c[a.tile] -= 4 if n >= 4 else 3
            delta = 1
        else:                            # 补杠：碰升级成杠，面子数不变
            c[a.tile] -= 1
            delta = 0
        after = shanten(c, p.n_melds + delta, p.void)
        if after <= cur and rng.random() < 0.75:
            return a
    return None


def _maybe_pong(game, p, pongs, rng) -> Optional[Action]:
    """碰：碰完还要打一张，所以拿"碰后的向听"和当前向听比。"""
    if not pongs:
        return None
    cur = shanten(p.hand, p.n_melds, p.void)
    for a in pongs:
        c = list(p.hand)
        c[a.tile] -= 2
        after = shanten(c, p.n_melds + 1, p.void)
        if after < cur:
            return a                                    # 明确推进，就碰
        if after == cur and rng.random() < PONG_BASE:
            return a
    return None


def _choose_discard(game, p, discs, rng) -> Action:
    """从 `discard_analysis` 的结果里挑一张打。

    最优口径：向听最小 → 进张最多。并列时随机（天然的不确定性，不损失强度）；
    另外 BLUNDER 概率打次优，避免玩家把 AI 的出牌规律背下来。
    """
    rows = discard_analysis(p.hand, p.n_melds, p.void, left=game._left_counts(p.idx))
    by_idx = {r["idx"]: r for r in rows}
    allowed = [a for a in discs if a.tile in by_idx]
    if not allowed:
        return rng.choice(discs)
    best_st = min(by_idx[a.tile]["shanten"] for a in allowed)
    top = [a for a in allowed if by_idx[a.tile]["shanten"] == best_st]
    if rng.random() < BLUNDER and len(rows) > len(top):
        # 打一张次优：在同向听之外挑（只在还有余量时）
        worse = [r for r in rows if r["shanten"] > best_st]
        if worse:
            pick = rng.choice(worse)
            if pick["idx"] in by_idx:
                return Action("discard", pick["idx"])
    # 并列最优里随机（进张相同、向听相同，强度无损）
    return Action("discard", rng.choice(top).tile)
