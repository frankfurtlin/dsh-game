"""德扑单挑训练器 CLI —— 练决策的核心界面。

每次轮到你行动时, 显示:
  - 你的手牌 / 公共牌 / 底池 / 双方筹码
  - 实时 equity (对随机手牌蒙特卡洛)
  - 底池赔率所需的跟注阈值
  - 跟注 EV
  - GTO 近似建议动作 (供对照, 你可以不采纳)

命令: fold(f) / check(k) / call(c) / raise <额> (r) / equity(eq) / help(h) / quit(q)
"""
import random
import sys

from .cards import Card
from .game import Hand, Action, PREFLOP, FLOP, TURN, RIVER, STREET_NAMES
from .evaluator import evaluate_best, category_name
from .equity import equity_vs_random, pot_odds, ev_call
from .ai import decide, STYLES

ITERS = 5000          # 决策辅助的蒙特卡洛次数
AI_ITERS = 3000


def _fmt_cards(cards):
    return " ".join(c.code for c in cards)


def _fmt_hole(hole):
    a, b = hole
    marker = "同花" if a.suit == b.suit else ""
    return f"{a.code} {b.code} {('('+marker+')') if marker else ''}"


def show_state(g, hero_idx, hero_equity=None, advice=None):
    me = hero_idx
    opp = 1 - me
    print("\n" + "═" * 56)
    print(f"  街: {STREET_NAMES[g.street]}   底池: {g.pot}")
    if g.board:
        print(f"  公共牌: {_fmt_cards(g.board)}")
    print(f"  你的手牌: {_fmt_hole(g.holes[me])}")
    print(f"  你筹码: {g.stacks[me]}   对手筹码: {g.stacks[opp]}")
    print(f"  本街你已投: {g.street_bet[me]}   对手已投: {g.street_bet[opp]}"
          f"   需跟: {max(0, g.current_bet - g.street_bet[me])}")
    if hero_equity is not None:
        print(f"  ── 决策辅助 ──")
        print(f"  实时胜率(对随机手牌): {hero_equity.equity:.1%}  "
              f"(胜{hero_equity.win:.1%}/平{hero_equity.tie:.1%})")
        to_call = g.current_bet - g.street_bet[me]
        if to_call > 0:
            need = pot_odds(to_call, g.pot)
            ev = ev_call(hero_equity.equity, g.pot, to_call)
            print(f"  底池赔率要求胜率 ≥ {need:.1%}   (跟注 {to_call} 看 {g.pot})")
            print(f"  跟注 EV ≈ {ev:+.1f} 筹码  "
                  f"{'✅ 正EV' if ev > 0 else '❌ 负EV'}")
        if advice:
            print(f"  GTO近似建议: {advice}")
    print("═" * 56)


def parse_input(s, g, idx):
    s = s.strip().lower()
    legal = g.legal_actions()
    kinds = {a.kind for a in legal}
    if s in ("f", "fold", "弃牌"):
        return Action("fold")
    if s in ("k", "check", "过牌"):
        if "check" not in kinds:
            print("  ⚠ 当前有下注, 不能过牌")
            return None
        return Action("check")
    if s in ("c", "call", "跟"):
        if "call" not in kinds:
            print("  ⚠ 当前无需跟注 (可用 check)")
            return None
        return next(a for a in legal if a.kind == "call")
    if s in ("h", "help", "?"):
        print("  命令: fold(f) check(k) call(c) raise <额>(r) equity(eq) help(h) quit(q)")
        return None
    if s.startswith(("r", "raise", "加")):
        parts = s.replace("raise", "r").replace("加注", "r").replace("加", "r").split()
        amt = None
        for p in parts[1:]:
            try:
                amt = int(p)
            except ValueError:
                pass
        if amt is None:
            print(f"  用法: raise <本街总额>  例: raise 20")
            return None
        raises = [a for a in legal if a.kind == "raise"]
        if not raises:
            print("  ⚠ 当前不能加注 (筹码不足或已全下)")
            return None
        exact = [a for a in raises if a.amount == amt]
        if exact:
            return exact[0]
        print(f"  ⚠ 非法加注额。合法: "
              f"{sorted(set(a.amount for a in raises))} (最小/全下)")
        return None
    print("  ⚠ 无法识别命令, 输入 h 看帮助")
    return None


def advice_for(g, hero_idx, n_opp=1):
    """用 GTO 近似给出建议动作(不执行)。"""
    a = decide(g, hero_idx, equity_vs_random, style="gto_approx", iters=2500,
               n_opponents=n_opp)
    return repr(a)


def play_session(hero_style="gto_approx", ai_style="loose_aggressive",
                 stacks=200, sb_bb=(1, 2), n_hands=None, seed=None,
                 auto_equity=True, n_players=2):
    rng = random.Random(seed)
    start_total = stacks * n_players
    hand_no = 0
    print("=" * 56)
    print("  德扑训练器  (你 vs AI)" + (f"  共 {n_players} 人" if n_players > 2 else ""))
    print(f"  对手风格: {ai_style} — {STYLES.get(ai_style, '')}")
    print("  输入 h 查看命令。目标: 长期盈利 + 提高决策质量。")
    print("=" * 56)

    while True:
        hand_no += 1
        if n_hands and hand_no > n_hands:
            break
        g = Hand([stacks] * n_players, button=(hand_no - 1) % n_players,
                 sb=sb_bb[0], bb=sb_bb[1], rng=rng)
        hero_idx = 0

        print(f"\n\n████ 第 {hand_no} 手  (按钮=P{g.button}, 你=P0) ████")
        print(f"你: {_fmt_hole(g.holes[hero_idx])}")

        guard = 0
        while g.to_act is not None and guard < 800:
            guard += 1
            idx = g.to_act
            if idx == hero_idx:
                eq = None
                adv = None
                if auto_equity:
                    n_opp = max(1, sum(1 for j in range(g.n) if j != hero_idx and g.in_hand[j]))
                    eq = equity_vs_random(g.holes[hero_idx], g.board, iters=ITERS,
                                          n_opponents=n_opp)
                    adv = advice_for(g, hero_idx, n_opp)
                show_state(g, hero_idx, eq, adv)
                while True:
                    raw = input(">> ")
                    a = parse_input(raw, g, hero_idx)
                    if a is not None:
                        break
                g.apply(a)
                if a.kind == "fold":
                    print("  你弃牌。")
            else:
                n_opp = max(1, sum(1 for j in range(g.n) if j != idx and g.in_hand[j]))
                a = decide(g, idx, equity_vs_random, style=ai_style, iters=AI_ITERS,
                           n_opponents=n_opp)
                print(f"  P{idx} 行动: {a}")
                g.apply(a)

        if g.result:
            print(f"\n  ▶ {g.describe_result()}")
            print(f"  ▶ 你这手后筹码: {g.stacks[hero_idx]} "
                  f"(净 {g.stacks[hero_idx]-stacks:+d})")
            if g.result["showdown"]:
                others = [j for j in range(g.n) if j != hero_idx and g.in_hand[j]]
                if others:
                    print(f"  ▶ 摊牌: " + ", ".join(
                        f"P{j} {_fmt_hole(g.holes[j])}" for j in others))

        if g.stacks[hero_idx] <= 0:
            print("\n  💀 你输光了! 会话结束。")
            break

    print("\n" + "=" * 56)
    print(f"  会话结束: 共 {hand_no} 手")
    print(f"  (注: 每手独立 {stacks} 筹码起步, 用于练决策而非累积资金)")
    print("=" * 56)


def demo_autoplay(n_hands=300, seed=7, n_players=2):
    """无交互自测: GTO 打松凶, 看整体盈亏。"""
    rng = random.Random(seed)
    net = 0
    for h in range(n_hands):
        g = Hand([200] * n_players, button=h % n_players, rng=rng)
        guard = 0
        while g.to_act is not None and guard < 800:
            idx = g.to_act
            style = "gto_approx" if idx == 0 else "loose_aggressive"
            n_opp = max(1, sum(1 for j in range(g.n) if j != idx and g.in_hand[j]))
            a = decide(g, idx, equity_vs_random, style=style, iters=1500,
                       n_opponents=n_opp)
            g.apply(a)
            guard += 1
        assert g.result
        net += g.stacks[0] - 200
    print(f"GTO vs 松凶 {n_hands} 手 ({n_players}人): 英雄净 {net:+d} 筹码 "
          f"({net/n_hands:+.1f}/手)")


if __name__ == "__main__":
    args = sys.argv[1:]
    # 解析可选人数: 形如 "6" 或 "n6" 表示 6 人桌
    n_players = 2
    rest = []
    for a in args:
        if a.startswith("n") and a[1:].isdigit():
            n_players = max(2, min(6, int(a[1:])))
        else:
            rest.append(a)
    args = rest
    if args and args[0] == "demo":
        hands = int(args[1]) if len(args) > 1 else 300
        demo_autoplay(hands, n_players=n_players)
    else:
        play_session(ai_style="loose_aggressive", n_players=n_players)
