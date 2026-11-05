"""多人(2-6) AI 自搏测试: 每手所有座位都是 AI, 验证引擎+equity+AI 组合可用、
筹码守恒、无非法动作、能正常结算。

用法: python3 test_multiway.py [hands_per_n] [iters]
"""
import random
import sys

from .game import Hand, Action
from .ai import decide, STYLES
from .equity import equity_vs_random

RNG = random.Random(4242)
STYLE_LIST = ["tight_passive", "loose_aggressive", "gto_approx"]


def play_hand(n, stacks0=200, iters=200):
    stacks = [stacks0] * n
    g = Hand(stacks, button=RNG.randrange(n), rng=RNG)
    guard = 0
    while g.to_act is not None and guard < 800:
        idx = g.to_act
        style = STYLE_LIST[idx % len(STYLE_LIST)]
        n_opp = max(1, sum(1 for j in range(g.n) if j != idx and g.in_hand[j]))
        a = decide(g, idx, equity_vs_random, style=style, iters=iters,
                   n_opponents=n_opp)
        legal = g.legal_actions()
        assert any(x.kind == a.kind and (a.kind != "raise" or x.amount == a.amount)
                   for x in legal), f"非法动作 {a} / legal={legal}"
        g.apply(a)
        guard += 1
    assert g.result is not None, "未结算"
    assert sum(g.stacks) == stacks0 * n, f"筹码不守恒 {g.stacks}"
    return g


if __name__ == "__main__":
    hands = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    iters = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    for n in (2, 3, 4, 5, 6):
        wins = [0] * n
        showdowns = 0
        for _ in range(hands):
            g = play_hand(n, iters=iters)
            if g.result["showdown"]:
                showdowns += 1
            for w in g.result["winners"]:
                if w is not None:
                    wins[w] += 1
        print(f"n={n}: {hands} 手通过 ✓  摊牌 {showdowns}  获胜分布 {wins}")
    print("MULTIWAY AI SELF-PLAY TESTS PASSED")
