"""game + ai 集成测试: AI 互搏, 验证可玩性 + 风格强弱关系。"""
import random
import sys

from .cards import Card
from .game import Hand, Action, PREFLOP
from .ai import decide, STYLES
from .equity import equity_vs_random, equity

RNG = random.Random(99)


def play_hand(stacks, button, style0, style1, iters=2000):
    g = Hand(stacks, button=button, rng=RNG)
    guard = 0
    while g.to_act is not None and guard < 300:
        idx = g.to_act
        style = style0 if idx == 0 else style1
        a = decide(g, idx, equity_vs_random, style=style, iters=iters)
        g.apply(a)
        guard += 1
    assert g.result is not None
    assert sum(g.stacks) == sum(stacks), f"筹码不守恒 {g.stacks}"
    return g


def test_ai_runs():
    for (s0, s1) in [("tight_passive", "loose_aggressive"),
                     ("gto_approx", "tight_passive"),
                     ("gto_approx", "loose_aggressive")]:
        g = play_hand([200, 200], 0, s0, s1, iters=800)
        print(f"  [ok] {s0} vs {s1} -> {g.describe_result()}, stack={g.stacks}")
    print("  [ok] AI 对局可运行 + 筹码守恒")


def test_style_strength():
    """同风格互搏应接近 50/50; GTO 对紧弱应占优。"""
    def winrate(s0, s1, n=60):
        w0 = 0
        for h in range(n):
            stacks = [200, 200]
            g = play_hand(stacks, h % 2, s0, s1, iters=500)
            winners = g.result["winners"]
            if winners == [0]:
                w0 += 1
        return w0 / n

    same = winrate("gto_approx", "gto_approx", n=40)
    print(f"  同风格 GTO vs GTO 胜率(P0): {same:.2f} (应≈0.50)")
    assert 0.30 <= same <= 0.70, f"同风格偏离过大: {same}"

    gto_vs_tp = winrate("gto_approx", "tight_passive", n=60)
    print(f"  GTO vs 紧弱 胜率(P0): {gto_vs_tp:.2f}")
    assert gto_vs_tp >= 0.45, f"GTO 不应明显弱于紧弱: {gto_vs_tp}"
    print("  [ok] 风格强弱关系基本合理")


def test_legal_never_raises_when_cannot():
    """确认 AI 不会选择不存在的动作。"""
    for _ in range(200):
        g = play_hand([200, 200], 0, "gto_approx", "loose_aggressive", iters=300)
    print("  [ok] 200 局无非法动作")


def test_no_pure_tell():
    """每个牌力档位都不能只有单一动作 —— 否则「跟注」就等于「有牌」, 一眼读死。

    这是用户反馈的问题: 原来三个风格全是确定性阈值(达到底池赔率就跟注、从不诈唬、
    强牌从不慢打), 于是每个动作都精确对应一个牌力区间, 打几手就能学会。
    这里在**固定牌力**下反复问 AI, 直接检查动作分布里有没有混合。

    注意构造局面时要连 pot 一起设: pot 由 total_bet 决定, 只调 current_bet 会得到
    离谱的底池赔率(我第一次就踩了 —— pot=4 配 to_call=30, 需要 88% 胜率,
    于是 strength=0.8 也弃牌, 看着像 bug 其实是对的)。
    """
    from .ai import _pot_odds_needed

    class StubEq:
        """把 equity 固定成指定值, 便于逐档位扫描。"""
        def __init__(self):
            self.equity = 0.0

        def __call__(self, *a, **k):
            return self

    def flop_state():
        g = Hand([200, 200], button=0, rng=random.Random(5))
        guard = 0
        while g.street == PREFLOP and g.to_act is not None and guard < 20:
            legal = g.legal_actions()
            a = (next((x for x in legal if x.kind == "call"), None)
                 or next(x for x in legal if x.kind == "check"))
            g.apply(a)
            guard += 1
        return g

    def dist(style, strength, to_call, pot=40, n=600):
        g = flop_state()
        idx = g.to_act
        g.total_bet = [pot // 2, pot - pot // 2]      # pot 是 total_bet 之和
        g.current_bet = g.street_bet[idx] + to_call
        stub = StubEq()
        stub.equity = strength
        rng = random.Random(4321)
        out = {}
        for _ in range(n):
            a = decide(g, idx, stub, style=style, rng=rng, n_opponents=1)
            out[a.kind] = out.get(a.kind, 0) + 1
        return {k: round(v / n, 3) for k, v in out.items()}

    # pot=40 时跟 10 → 需要 20% 胜率
    assert abs(_pot_odds_needed(10, 40) - 0.2) < 1e-9

    for style in ("tight_passive", "loose_aggressive", "gto_approx"):
        weak, mid, strong = (dist(style, s, to_call=10) for s in (0.10, 0.50, 0.95))
        print(f"  {style}: 弱{weak} 中{mid} 强{strong}")
        # ① 强牌偶尔只跟注(慢打) → 「跟注」不总是弱
        assert strong.get("call", 0) > 0.05, f"{style}: 强牌从不慢打 {strong}"
        # ② 弱牌偶尔加注(诈唬) → 「加注」不总是强
        assert weak.get("raise", 0) > 0.01, f"{style}: 弱牌从不诈唬 {weak}"
        # ③ 每个档位都不是单一动作 —— 这才是「读不死」的本质
        for s, d in (("弱", weak), ("中", mid), ("强", strong)):
            assert len(d) >= 2, f"{style} {s}牌只有单一动作 {d}"
    # ④ 无人下注时: 进攻型风格会用弱牌下注、也会用强牌过牌设陷阱
    for style in ("loose_aggressive", "gto_approx"):
        assert dist(style, 0.10, to_call=0).get("raise", 0) > 0.05, f"{style}: 无下注时弱牌从不下注"
        assert dist(style, 0.95, to_call=0).get("check", 0) > 0.05, f"{style}: 无下注时强牌从不过牌"
    print("  [ok] 各档位均有混合: 「跟注=好牌」的破绽已消除")


if __name__ == "__main__":
    test_ai_runs()
    test_style_strength()
    test_legal_never_raises_when_cannot()
    test_no_pure_tell()
    print("ALL GAME/AI TESTS PASSED")
