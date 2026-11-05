"""蒙特卡洛权益(equity)计算 —— 德扑决策的数学地基。

给定英雄手牌 + 公共牌 (+ 对手范围)，随机补齐剩余公共牌与对手手牌，
估算 胜 / 平 / 负 概率。

equity 定义(常见口径):
    equity = win + tie / (在平局中共享底池的人数)
本模块按 heads-up(villain 数量) 通用实现: 若 n 家平局则每家 tie/n。

纯标准库; workers>1 时用进程池加速。
"""
import random
from concurrent.futures import ProcessPoolExecutor

from .cards import Card, make_deck
from .evaluator import evaluate_best


class Equity:
    __slots__ = ("win", "tie", "lose", "iters")

    def __init__(self, win, tie, lose, iters):
        self.win, self.tie, self.lose, self.iters = win, tie, lose, iters

    @property
    def equity(self):
        """胜率份额: win + tie 的一半(单挑)。"""
        return self.win + self.tie / 2

    def __repr__(self):
        return (f"Equity(win={self.win:.4f} tie={self.tie:.4f} "
                f"lose={self.lose:.4f} equity={self.equity:.4f})")


def _remaining_deck(known_codes):
    used = set(known_codes)
    return [c for c in make_deck() if c.code not in used]


def _simulate_chunk(args):
    """进程池 worker: 用牌码字符串重建, 支持 1..N 个随机对手(多人底池)。"""
    hero_codes, board_codes, villain_codes, n_opponents, iters, seed = args
    rng = random.Random(seed)
    hero = [Card(c) for c in hero_codes]
    board = [Card(c) for c in board_codes]
    vrange = None
    if villain_codes is not None:
        vrange = [(Card(a), Card(b)) for (a, b) in villain_codes]

    known = hero_codes + board_codes
    need_board = 5 - len(board)
    base_deck = _remaining_deck(known)

    wins = ties = losses = 0
    rnd = rng.randrange
    for _ in range(iters):
        deck = base_deck[:]
        n = len(deck)
        # 抽样所有对手手牌(从剩余牌堆取 2*N 张)
        if vrange is not None:
            avail = {c.code for c in deck}
            combos = [(a, b) for (a, b) in vrange
                      if a.code in avail and b.code in avail]
            if not combos:
                continue
            a, b = rng.choice(combos)
            villains = [[a, b]]
            deck = [c for c in deck if c.code not in (a.code, b.code)]
            n = len(deck)
        else:
            villains = []
            for _ in range(n_opponents):
                if n < 2:
                    break
                i = rnd(n); deck[i], deck[n - 1] = deck[n - 1], deck[i]; n -= 1; c1 = deck[n]
                j = rnd(n); deck[j], deck[n - 1] = deck[n - 1], deck[j]; n -= 1; c2 = deck[n]
                villains.append([c1, c2])
        # 补公共牌: 与对手牌共用同一段 Fisher-Yates 前缀。
        # 关键: 必须把公共牌也「抽」出来, 不能取剩余牌堆的末尾 —— 只做 2*N 步交换时
        # 剩余牌堆几乎没被打乱, 取末尾等于取原始顺序, 公共牌分布会严重偏移。
        board_run = list(board)
        for _ in range(need_board):
            if n == 0:
                break
            i = rnd(n); deck[i], deck[n - 1] = deck[n - 1], deck[i]; n -= 1
            board_run.append(deck[n])
        hero7 = hero + board_run
        hr = evaluate_best(hero7)
        best_v = None
        for vill in villains:
            vr = evaluate_best(vill + board_run)
            if best_v is None or vr > best_v:
                best_v = vr
        # 多路底池: 只要有人比英雄强就算英雄"不赢"(简化口径)
        if hr > best_v:
            wins += 1
        elif hr == best_v:
            ties += 1
        else:
            losses += 1
    return wins, ties, losses


def equity(hero, board, villain_range=None, iters=10000, rng=None, workers=1,
           n_opponents=1):
    """估算 equity。

    hero: List[Card] 两张
    board: List[Card] 0/3/4/5 张
    villain_range: None=随机手牌; 或 [(Card,Card), ...] 对手可能范围
    n_opponents: 随机对手数量(多人底池, 默认 1=单挑)
    """
    assert len(hero) == 2, "英雄必须是两张手牌"
    assert len(board) <= 5
    assert n_opponents >= 1
    hero_codes = [c.code for c in hero]
    board_codes = [c.code for c in board]
    villain_codes = None
    if villain_range is not None:
        villain_codes = [(a.code, b.code) for (a, b) in villain_range]

    rng = rng or random

    if workers <= 1:
        seed = rng.randrange(2 ** 31)
        w, t, l = _simulate_chunk(
            (hero_codes, board_codes, villain_codes, n_opponents, iters, seed))
    else:
        chunk = max(1, iters // workers)
        jobs = []
        for k in range(workers):
            n = chunk if k < workers - 1 else iters - chunk * (workers - 1)
            jobs.append((hero_codes, board_codes, villain_codes, n_opponents, n,
                         rng.randrange(2 ** 31)))
        w = t = l = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for rw, rt, rl in ex.map(_simulate_chunk, jobs):
                w += rw; t += rt; l += rl

    total = max(1, w + t + l)
    return Equity(w / total, t / total, l / total, total)


# ---------- 便捷: 常见场景 ----------

def equity_vs_random(hero, board, iters=10000, workers=1, rng=None,
                    n_opponents=1):
    return equity(hero, board, None, iters, rng, workers, n_opponents)


def equity_vs_hand(hero, board, villain_hole, iters=10000, workers=1, rng=None):
    """对手牌已知(读牌/复盘用)。"""
    return equity(hero, board, [(villain_hole[0], villain_hole[1])],
                  iters, rng, workers)


def pot_odds(call_amount, pot_before_call):
    """底池赔率: 需要多少胜率才值得跟。返回所需 equity 阈值。"""
    return call_amount / (pot_before_call + call_amount)


def ev_call(equity_value, pot_before_call, call_amount):
    """跟注 EV = eq*(pot+call) - (1-eq)*call  ... 简化口径(eq 已含摊牌份额)。"""
    return equity_value * (pot_before_call + call_amount) - (1 - equity_value) * call_amount


def ev_fold():
    return 0.0


if __name__ == "__main__":
    from .evaluator import category_name
    def C(s):
        return [Card(x) for x in s.split()]

    print("AA preflop vs random:", equity_vs_random(C("As Ad"), [], iters=20000))
    print("72o preflop vs random:", equity_vs_random(C("7s 2d"), [], iters=20000))
    print("AKs preflop vs random:", equity_vs_random(C("As Ks"), [], iters=20000))
    print("AA vs KK preflop   :", equity_vs_hand(C("As Ad"), [], C("Ks Kd"), iters=20000))
    print("flop FD  equity    :", equity_vs_random(C("As Ks"), C("9s 4s 2h"), iters=20000))
