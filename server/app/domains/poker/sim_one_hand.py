"""模拟一整局德扑: 英雄用 GTO 近似决策(代表"理性打法"), 对手松凶。
逐步打印每个决策点的数字, 像旁观者一样看完整一手。
"""
import random

from .cards import Card
from .game import Hand, STREET_NAMES, PREFLOP, FLOP, TURN, RIVER
from .equity import equity_vs_random
from .ai import decide

RNG = random.Random(100)


def show_decisions(g, hero_idx):
    me = hero_idx
    opp = 1 - me
    to_call = g.current_bet - g.street_bet[me]
    eq = equity_vs_random(g.holes[me], g.board, iters=4000)
    # 英雄会怎么选(GTO近似)
    adv = decide(g, me, equity_vs_random, style="gto_approx", iters=1500)
    print(f"  你的手牌: {g.holes[me][0].code} {g.holes[me][1].code}")
    if g.board:
        print(f"  公共牌:   {' '.join(c.code for c in g.board)}")
    print(f"  底池 {g.pot}  你筹码 {g.stacks[me]}  需跟 {to_call}")
    print(f"  ⟶ 实时胜率 {eq.equity:.1%}  底池赔率要求 ≥ "
          f"{(to_call/(g.pot+to_call) if to_call else 0):.1%}")
    if to_call:
        print(f"  ⟶ 跟注 EV ≈ {eq.equity*(g.pot+to_call)-(1-eq.equity)*to_call:+.1f}")
    print(f"  ⟶ GTO建议: {adv}")


def main():
    g = Hand([200, 200], button=0, rng=RNG)   # 你是按钮=小盲, 翻牌前先动
    hero_idx = 0
    print("═" * 60)
    print("  模拟一局: 你(英雄, GTO近似) vs AI(松凶)")
    print("  起始: 你 200 / AI 200, 盲注 1/2, 你是按钮(翻牌前先动)")
    print("═" * 60)
    print(f"  [手牌] 你: {g.holes[0][0].code} {g.holes[0][1].code}   "
          f"AI: {g.holes[1][0].code} {g.holes[1][1].code}  (隐藏)")
    print(f"  [翻牌前] 强制盲注: 你(SB)下1, AI(BB)下2, 底池=3")

    guard = 0
    last_street = None
    while g.to_act is not None and guard < 400:
        guard += 1
        idx = g.to_act
        if g.street != last_street:
            last_street = g.street
            tag = "翻牌前" if g.street == PREFLOP else STREET_NAMES[g.street]
            print(f"\n  ────── {tag} ──────")

        if idx == hero_idx:
            show_decisions(g, hero_idx)
            a = decide(g, idx, equity_vs_random, style="gto_approx", iters=2000)
            print(f"  [你] 选择: {a}")
            g.apply(a)
        else:
            a = decide(g, idx, equity_vs_random, style="loose_aggressive", iters=1500)
            print(f"  [AI] 行动: {a}")
            g.apply(a)

    print("\n" + "═" * 60)
    r = g.result
    ranks = r.get("ranks") or {}                      # {座位: 牌型}，仅摊牌时有
    payouts = r.get("payouts") or []                  # 每个座位从池子里拿回多少
    if r["showdown"]:
        print(f"  ▶ 摊牌! 你 {ranks.get(str(hero_idx), '?')} | "
              f"AI {ranks.get('1', '?')}")
        print(f"  ▶ AI 牌: {g.holes[1][0].code} {g.holes[1][1].code}")
    else:
        print(f"  ▶ 对手弃牌, {'你' if r['winners'] == [hero_idx] else 'AI'}赢下底池")
    ws = [w for w in r["winners"] if w is not None]
    if len(ws) > 1:                                   # 多人拿钱：可能平局，也可能分边池
        who = "、".join("你" if w == hero_idx else f"P{w}" for w in ws)
        got = "、".join(f"+{payouts[w]}" for w in ws) if payouts else ""
        print(f"  ▶ 结果: {who} 分得底池 {r['pot']}（{got}）"
              f"{'，摊牌平局' if r.get('tie') else '，各赢一层边池'}")
    elif ws:
        w = ws[0]
        amt = payouts[w] if payouts else r["pot"]
        print(f"  ▶ 结果: {'你' if w == hero_idx else 'AI'}赢得 {amt} 底池")
    print(f"  ▶ 你最终筹码: {g.stacks[hero_idx]} (净 {g.stacks[hero_idx]-200:+d})")
    print("═" * 60)


if __name__ == "__main__":
    main()
