"""AI 决策模块 —— 三种风格, 均基于 equity 与底池赔率。

你是和这些 AI 对练的"英雄", 所以它们的决策逻辑透明、可调权重,
方便你理解"数学最优"长什么样、以及不同风格如何偏离它。

风格:
- tight_passive : 紧弱 —— 只玩强牌, 被动跟注, 极少诈唬
- loose_aggressive: 松凶 —— 宽范围入局, 高频加注施压, 善用手牌外下注
- gto_approx    : GTO 近似 —— 按 equity 与底池赔率算 EV 决策, 加注频率随 equity 单调

决策接口: decide(game, player_idx, equity_fn) -> Action
equity_fn(hero_hole, board, iters) 注入, 避免 AI 直接依赖蒙特卡洛实现。

关于混合策略(mix):
原来三个风格全是**确定性阈值** —— 例如 GTO 近似里"equity 达到底池赔率就跟注、
超过 0.7 才加注、从不诈唬"。这样打出来每个动作都等价于一个牌力区间,
玩家很快就能学会"他跟我就是有牌、他加注就是大牌", 对练价值大打折扣。
现在每个档位都留了混合: 强牌偶尔慢打(让"跟注"不总是弱)、弱牌偶尔诈唬
(让"加注"不总是强)、边缘牌偶尔直接弃。随机源由调用方传入, 一局之内可复现。
"""
import random
from typing import Optional

from .evaluator import category_name
from .game import Action, PREFLOP, FLOP, TURN, RIVER

# decide() 没拿到 rng 时用的兜底随机源（实战走这里；测试传自己的 Random 以便复现）。
_DEFAULT_RNG = random.Random()

# 翻牌前起手牌范围评估(极简 1-2 档): 用点数粗略判断是否为"强牌"
_STRONG_HOLE_PAIRS = {"AA", "KK", "QQ", "JJ", "TT"}
_STRONG_HOLE_SUITED = {"AK", "AQ", "AJ", "KQ", "AT"}
_BROADWAY = set("AKQJT")


def _hole_strength(hole):
    """返回 0~1 的起手强度(仅 preflop 用)。"""
    a, b = hole
    pa, pb = a.rv, b.rv
    pair = pa == pb
    suited = a.suit == b.suit
    high = (pa >= 10 and pb >= 10) or (pa in _BROADWAY and pb in _BROADWAY)
    if pair and pa >= 10:
        return 1.0
    if pair:
        return 0.7
    if {pa, pb} in ({14, 13}, {14, 12}, {14, 11}) and suited:
        return 0.95
    if high and suited:
        return 0.75
    if high:
        return 0.55
    if suited:
        return 0.35
    return 0.2


def _pot_odds_needed(call_amount, pot):
    if call_amount <= 0:
        return 0.0
    return call_amount / (pot + call_amount)


def _pick_action(game, idx, kind, amount=0, is_allin=False):
    """根据 game 的 legal_actions 返回匹配的合法 Action 实例。"""
    legal = game.legal_actions()
    if kind == "raise":
        raises = [a for a in legal if a.kind == "raise"]
        if raises:
            exact = [a for a in raises if a.amount == amount]
            if exact:
                return exact[0]
            return min(raises, key=lambda x: abs(x.amount - amount))
    # fold/check/call: 按类型取(金额可能被全下夹紧)
    same = [a for a in legal if a.kind == kind]
    if same:
        return same[0]
    return legal[0]


def decide(game, idx, equity_fn, style="gto_approx", iters=4000, n_opponents=1,
           rng=None, mix=True):
    """返回 AI 选择的 Action。

    equity_fn(hole: List[Card], board: List[Card], iters, n_opponents) -> Equity

    mix=True(默认, 实战用): 按概率混合动作(见模块 docstring)。rng 传对局的随机源,
      同一局可复现。
    mix=False: 退回确定性阈值。**给"决策辅助"用** —— 那是给玩家看的建议,
      每次刷新都在"跟注/加注"之间跳变会让人没法读, 所以建议必须稳定。
    """
    legal = game.legal_actions()
    if not legal:
        return Action("fold")
    to_call = game.current_bet - game.street_bet[idx]
    pot = game.pot

    # 翻牌前: 用范围强度(避免每次都蒙特卡洛, 更快也更稳)
    if game.street == PREFLOP:
        strength = _hole_strength(game.holes[idx])
    else:
        eq = equity_fn(game.holes[idx], game.board, iters, n_opponents=n_opponents)
        strength = eq.equity

    # 一次均匀抽样决定这手走哪条分支 —— 等价于在动作集合上按概率做分类抽样。
    r = (rng or _DEFAULT_RNG).random() if mix else None

    if style == "tight_passive":
        return _tight_passive(game, idx, legal, strength, to_call, pot, r)
    if style == "loose_aggressive":
        return _loose_aggressive(game, idx, legal, strength, to_call, pot, r)
    return _gto_approx(game, idx, legal, strength, to_call, pot, r)


def _tight_passive(game, idx, legal, strength, to_call, pot, r):
    """紧弱: 只玩强牌、被动跟注、极少诈唬。

    "极少"不等于"从不": 全确定性会让对手学出"他一加注就是坚果"。
    所以留了约 3% 的诈唬加注, 以及满牌时 30% 的慢打。
    """
    has_raise = _can_raise(game, legal)
    if to_call <= 0:
        if not has_raise:
            return _pick_action(game, idx, "check")
        if strength >= 0.85:
            cut = 0.75
        elif strength >= 0.6:
            cut = 0.20
        else:
            cut = 0.0
        if cut and (r is None or r < cut):
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "check")
    # 需跟注
    if strength >= 0.9 and has_raise:
        if r is None or r < 0.70:
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "call", to_call)
    if strength >= 0.75:
        if has_raise and (r is None or r < 0.35):
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "call", to_call)
    if strength >= 0.55:
        # 边缘牌偶尔直接弃 —— 不让"跟注"等价于"有牌"
        if r is not None and r < 0.20:
            return _pick_action(game, idx, "fold")
        return _pick_action(game, idx, "call", to_call)
    if has_raise and r is not None and r < 0.03:
        return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
    return _pick_action(game, idx, "fold")


def _loose_aggressive(game, idx, legal, strength, to_call, pot, r):
    """松凶: 宽范围入局、高频加注施压 —— 诈唬频率最高, "加注"几乎不代表牌力。

    但也要有慢打, 否则"跟注"又会变成强牌信号。
    """
    needed = _pot_odds_needed(to_call, pot)
    has_raise = _can_raise(game, legal)
    if to_call <= 0:
        if not has_raise:
            return _pick_action(game, idx, "check")
        if strength >= 0.7:
            cut = 0.85
        elif strength >= 0.35:
            cut = 0.55
        else:
            cut = 0.25          # 空气也高频下注施压
        if r is None or r < cut:
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "check")
    if strength >= 0.8:
        if has_raise and (r is None or r < 0.60):   # 偶尔慢打
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "call", to_call)
    if strength >= max(needed - 0.05, 0.5):
        if has_raise and (r is None or r < 0.50):
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "call", to_call)
    if strength >= needed - 0.05:
        # 同上: 三段概率区间互不重叠, 否则边缘弃牌的区间会被加注包住、永远走不到
        raise_p = 0.30
        fold_p = 0.20 if strength <= needed + 0.05 else 0.0
        if has_raise and r is not None and r < raise_p:
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        if r is not None and raise_p <= r < raise_p + fold_p:
            return _pick_action(game, idx, "fold")
        if r is None and has_raise:
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "call", to_call)
    if has_raise and (r is None or r < 0.20):
        return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
    return _pick_action(game, idx, "fold")


def _gto_approx(game, idx, legal, strength, to_call, pot, r):
    """GTO 近似: 用底池赔率算阈值, 再在阈值附近混合。

    原实现是"达到赔率就跟、equity>=0.7 才加注"的纯确定性策略 —— 于是
    "跟注"等价于"有牌", 玩家一眼读死。现在: 满牌 25% 慢打(跟注也可能是坚果)、
    不够赔率时 12% 诈唬加注、刚好卡线的边缘牌 15% 直接弃。三个档位都不再是单一动作。
    """
    needed = _pot_odds_needed(to_call, pot)
    has_raise = _can_raise(game, legal)
    if to_call <= 0:
        if not has_raise:
            return _pick_action(game, idx, "check")
        if strength >= 0.75:
            cut = 0.80
        elif strength >= 0.50:
            cut = 0.50
        elif strength >= 0.30:
            cut = 0.28
        else:
            cut = 0.15          # 空气偶尔诈唬下注
        if r is None or r < cut:
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "check")
    # 跟注阈值 = 底池赔率; 加注阈值更高
    if strength >= 0.85 and has_raise:
        # 怪兽牌 25% 慢打 —— 让"跟注"也可能是坚果
        if r is None or r >= 0.25:
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "call", to_call)
    if strength >= needed:
        # 会跟的牌里也要拿一部分去加注, 否则这一整档只有"跟注", 又成了可读信号。
        # 用一个抽样数切互不重叠的三段(加注 / 弃 / 跟注) —— 早先写成嵌套 if 时
        # fold 的区间被 raise 完全包住, 那个分支永远走不到。
        raise_p = 0.55 if strength >= 0.65 else 0.25
        fold_p = 0.15 if strength < needed + 0.10 else 0.0
        if has_raise and r is not None and r < raise_p:
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        if r is not None and raise_p <= r < raise_p + fold_p:
            return _pick_action(game, idx, "fold")
        if r is None and has_raise and strength >= 0.65:
            return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
        return _pick_action(game, idx, "call", to_call)
    if has_raise and r is not None and r < 0.12:
        return _pick_action(game, idx, "raise", _raise_to(game, legal, "min"))
    return _pick_action(game, idx, "fold")


# ---------- 工具 ----------
def _can_raise(game, legal):
    return any(a.kind == "raise" for a in legal)


def _raise_to(game, legal, mode="min"):
    raises = [a for a in legal if a.kind == "raise"]
    if not raises:
        return None
    if mode == "min":
        return min(a.amount for a in raises)
    return max(a.amount for a in raises)


STYLES = {
    "tight_passive": "紧弱 (Tight-Passive): 只玩强牌, 被动跟注, 极少诈唬",
    "loose_aggressive": "松凶 (Loose-Aggressive): 宽范围入局, 高频加注施压",
    "gto_approx": "GTO近似 (Equity/EV 驱动): 跟注阈值=底池赔率, 加注随equity单调",
}


if __name__ == "__main__":
    from .cards import Card
    # 各风格在简单场景下的选择(不跑蒙特卡洛, 用强度近似)
    print("风格说明:")
    for k, v in STYLES.items():
        print(f"  [{k}] {v}")
