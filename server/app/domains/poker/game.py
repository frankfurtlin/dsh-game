"""多人无限注德州下注状态机 (2–6 人, 支持边池 side pots)。

设计:
- 通用 N 人引擎: stacks/holes/pending 均为列表, 索引即座位。
- 盲注与行动顺序:
    N==2 : 按钮位 = 小盲(翻牌前先动, 翻牌后后动) — 与原单挑行为一致。
    N>=3 : 按钮左邻 = 小盲, 再左邻 = 大盲; 翻牌前从大盲左侧 UTG 开始,
           翻牌后从小盲开始。
- 下注轮结束: 用 pending 集合(本街仍需行动的玩家)精确判定, 兼容全下/不足额跟注。
- 边池: 摊牌时按每玩家累计 contrib 逐层剥离构建(见 _pots_from_contrib)。
- 无人能跟的多余下注: 在下注轮结束时按「最高注 - 次高注」退还(见 _refund_excess)。
- 筹码守恒是核心不变量(测试验证)。

术语:
- street_bet[i]: 本街已投入
- total_bet[i] : 本手已投入(展示/赔率用)
- contrib[i]   : 本手累计投入(边池分层用, 与 total_bet 数值一致)
- current_bet  : 本街需跟到的额度
- last_raise_size: 最近一次加注增量(决定最小加注)
"""
import random
from dataclasses import dataclass
from typing import List, Optional

from .cards import Card, make_deck
from .evaluator import evaluate_best, category_name

PREFLOP, FLOP, TURN, RIVER, SHOWDOWN = 0, 1, 2, 3, 4
STREET_NAMES = {PREFLOP: "翻牌前", FLOP: "翻牌", TURN: "转牌", RIVER: "河牌", SHOWDOWN: "摊牌"}


@dataclass
class Action:
    kind: str                 # fold / check / call / raise
    amount: int = 0           # call: 投入筹码; raise: 达到的本街总额
    is_allin: bool = False

    def __repr__(self):
        if self.kind == "raise":
            return f"加注到{self.amount}" + ("(全下)" if self.is_allin else "")
        if self.kind == "call":
            return f"跟注{self.amount}" + ("(全下)" if self.is_allin else "")
        if self.kind == "check":
            return "过牌"
        return "弃牌"


class Hand:
    """一手牌的状态机。stacks 为各玩家筹码; button 为按钮位索引。"""

    def __init__(self, stacks, button=0, sb=1, bb=2, deck=None, rng=None):
        self.n = len(stacks)
        self.sb, self.bb = sb, bb
        self.button = button % self.n
        self.stacks = list(stacks)
        self.contrib = [0] * self.n
        self.in_hand = [True] * self.n

        rng = rng or random
        d = deck if deck is not None else make_deck()
        if deck is None:
            rng.shuffle(d)
        self.deck = list(d)
        self.holes = [[self.deck.pop(), self.deck.pop()] for _ in range(self.n)]
        self.board: List[Card] = []

        self.street = PREFLOP
        self.street_bet = [0] * self.n
        self.total_bet = [0] * self.n
        self.folded = [False] * self.n
        self.all_in = [False] * self.n
        self.current_bet = 0
        self.last_raise_size = bb
        self.actions = []                       # (street, player, Action)
        self.result = None
        self.last_action = [None] * self.n      # 各玩家最近一次动作(展示用)

        # 盲注位
        if self.n == 2:
            self.sb_idx = self.button
            self.bb_idx = 1 - self.button
        else:
            self.sb_idx = (self.button + 1) % self.n
            self.bb_idx = (self.button + 2) % self.n
        self._commit(self.sb_idx, min(sb, self.stacks[self.sb_idx]))
        self._commit(self.bb_idx, min(bb, self.stacks[self.bb_idx]))
        self.current_bet = self.street_bet[self.bb_idx]

        self.pending = set(range(self.n))
        self._refresh_allin()
        self.to_act = self._first_to_act()

    # ---------- 内部 ----------
    def _commit(self, i, amt):
        amt = max(0, min(amt, self.stacks[i]))
        self.stacks[i] -= amt
        self.street_bet[i] += amt
        self.total_bet[i] += amt
        self.contrib[i] += amt

    def _refresh_allin(self):
        for i in range(self.n):
            if self.stacks[i] == 0:
                self.all_in[i] = True
                self.pending.discard(i)

    def _first_to_act(self):
        """本街首个行动者。"""
        if self.n == 2:
            first = self.sb_idx                 # 单挑: 小盲(按钮)先动
        elif self.street == PREFLOP:
            first = (self.bb_idx + 1) % self.n  # UTG
        else:
            first = self.sb_idx                 # 翻牌后从小盲开始
        if self.all_in[first] or not self.in_hand[first]:
            first = self._next_after(first)
        return first

    def _next_after(self, after):
        """返回 after 之后下一个待行动玩家(pending)。"""
        if not self.pending:
            return None
        start = (after + 1) % self.n
        for k in range(self.n):
            i = (start + k) % self.n
            if i in self.pending:
                return i
        return None

    @property
    def pot(self) -> int:
        return sum(self.total_bet)

    # ---------- 对外 ----------
    def legal_actions(self) -> List[Action]:
        if self.to_act is None or self.street == SHOWDOWN:
            return []
        i = self.to_act
        s = self.stacks[i]
        to_call = self.current_bet - self.street_bet[i]
        acts = []
        if to_call > 0:
            acts.append(Action("fold"))
            acts.append(Action("call", min(to_call, s), min(to_call, s) == s))
            max_to = self.street_bet[i] + s
            min_to = self.current_bet + self.last_raise_size
            if s > to_call:
                if min_to > max_to:
                    acts.append(Action("raise", max_to, True))
                else:
                    acts.append(Action("raise", min_to))
                acts.append(Action("raise", max_to, True))
        else:
            acts.append(Action("check"))
            if s > 0:
                min_to = max(self.bb, self.current_bet + self.last_raise_size)
                max_to = self.street_bet[i] + s
                if min_to >= max_to:
                    acts.append(Action("raise", max_to, True))
                else:
                    acts.append(Action("raise", min_to))
                    acts.append(Action("raise", max_to, True))
        seen, out = set(), []
        for a in acts:
            k = (a.kind, a.amount, a.is_allin)
            if k not in seen:
                seen.add(k)
                out.append(a)
        return out

    def apply(self, action: Action):
        i = self.to_act
        assert i is not None, "无待行动玩家"
        if action.kind == "fold":
            self.folded[i] = True
            self.in_hand[i] = False
            self.pending.discard(i)
        elif action.kind == "check":
            assert self.current_bet == self.street_bet[i], "有下注不能过牌"
            self.pending.discard(i)
        elif action.kind == "call":
            to_call = self.current_bet - self.street_bet[i]
            assert to_call > 0, "无需跟注"
            self._commit(i, min(to_call, self.stacks[i]))
            self.pending.discard(i)
        elif action.kind == "raise":
            assert action.amount > self.current_bet, "加注额必须高于当前注"
            old = self.current_bet
            self._commit(i, action.amount - self.street_bet[i])
            raise_size = self.street_bet[i] - old
            if raise_size > self.last_raise_size:
                self.last_raise_size = raise_size
            self.current_bet = self.street_bet[i]
            self.pending.discard(i)
            for j in range(self.n):
                if j != i and self.in_hand[j] and not self.all_in[j]:
                    self.pending.add(j)
        else:
            raise ValueError(f"未知动作 {action.kind}")

        self.last_action[i] = action
        self.actions.append((self.street, i, action))
        self._refresh_allin()
        for j in range(self.n):
            if self.folded[j]:
                self.pending.discard(j)

        if self._hand_over():
            return self._finish()
        if not self.pending:
            self._end_street()
        else:
            self.to_act = self._next_after(i)
        return None

    def _hand_over(self) -> bool:
        live = [j for j in range(self.n) if self.in_hand[j]]
        return len(live) <= 1

    def _end_street(self):
        self._refund_excess()
        live_notallin = [j for j in range(self.n) if self.in_hand[j] and not self.all_in[j]]
        if self.street == RIVER:
            return self._showdown()
        if len(live_notallin) < 2:
            # 少于两人还能下注 → 自动跑完剩余公共牌并摊牌
            return self._runout_if_allin()
        self.street += 1
        k = 3 if self.street == FLOP else 1
        for _ in range(k):
            self.board.append(self.deck.pop())
        self.street_bet = [0] * self.n
        self.current_bet = 0
        self.last_raise_size = self.bb
        self.pending = set(range(self.n))
        self._refresh_allin()
        for j in range(self.n):
            if not self.in_hand[j] or self.all_in[j]:
                self.pending.discard(j)
        self.to_act = self._first_to_act()

    def _refund_excess(self):
        """本条街唯一最高注超出次高注的部分无法被跟 → 退还给该玩家。"""
        if self.n < 2:
            return
        bets = sorted(self.street_bet, reverse=True)
        top, second = bets[0], bets[1]
        if top <= second:
            return
        for j in range(self.n):
            if self.street_bet[j] == top:
                refund = top - second
                self.stacks[j] += refund
                self.total_bet[j] -= refund
                self.contrib[j] -= refund
                self.street_bet[j] -= refund
                break

    def _runout_if_allin(self):
        while self.street != RIVER:
            self.street += 1
            k = 3 if self.street == FLOP else 1
            for _ in range(k):
                self.board.append(self.deck.pop())
        return self._showdown()

    # ---------- 边池 ----------
    @staticmethod
    def build_pots(contrib, in_hand):
        """按累计投入逐层剥离构建边池。
        返回 [(eligible_player_indices, amount), ...] —— 主池在前。"""
        c = list(contrib)
        pots = []
        while True:
            positive = [x for x in c if x > 0]
            if not positive:
                break
            lvl = min(positive)
            contributors = [j for j in range(len(c)) if c[j] >= lvl]
            amount = lvl * len(contributors)
            for j in contributors:
                c[j] -= lvl
            eligible = [j for j in contributors if in_hand[j]]
            if eligible:
                pots.append((eligible, amount))
        return pots

    def _showdown(self):
        """摊牌结算：逐池评牌分钱，并把「谁赢了多少、谁跟谁平分」记进 result。

        result 字段（前端结算弹窗与 CLI 都读它）：
          winners  —— 拿到过筹码的座位(升序)。多人时**不等于**平局：边池可能由
                      不同人赢下(各赢一层)，平局只看单个池是否被多人平分。
          pot      —— 本手底池总额。
          payouts  —— 每个座位从池子里拿回多少(含自己投入的部分)；sum == pot。
          pots     —— 逐池明细 [{amount, eligible, winners:[{seat,amount}], split}]，
                      split=True 表示这个池被同牌型的多人平分(即真正的平局)。
          ranks    —— 摊牌牌型 {座位: "两对"...}，用来解释「为什么他赢/为什么平」。
          tie      —— 是否出现过被平分的池。
        """
        self.street = SHOWDOWN
        self.to_act = None
        pots = self.build_pots(self.contrib, self.in_hand)
        winners_all = set()
        rank_cache = {}
        payouts = [0] * self.n
        detail = []
        for eligible, amount in pots:
            if amount <= 0:
                continue
            best, best_j = None, []
            for j in eligible:
                if j not in rank_cache:
                    rank_cache[j] = evaluate_best(self.holes[j] + self.board)
                r = rank_cache[j]
                if best is None or r > best:
                    best, best_j = r, [j]
                elif r == best:
                    best_j.append(j)
            share = amount // len(best_j)
            rem = amount - share * len(best_j)
            entries = []
            for k, j in enumerate(best_j):
                got = share + (rem if k == 0 else 0)
                self.stacks[j] += got
                payouts[j] += got
                winners_all.add(j)
                entries.append({"seat": j, "amount": got})
            detail.append({"amount": amount, "eligible": list(eligible),
                           "winners": entries, "split": len(best_j) > 1})
        self.result = {"showdown": True, "winners": sorted(winners_all),
                       "pot": sum(self.contrib), "payouts": payouts,
                       "pots": detail, "tie": any(p["split"] for p in detail),
                       "ranks": {str(j): category_name(rank_cache[j])
                                 for j in sorted(rank_cache)}}
        return self.result

    def _finish(self):
        """所有人弃牌只剩一家：不用亮牌，直接把池子给他。"""
        self.to_act = None
        self.street = SHOWDOWN
        live = [j for j in range(self.n) if self.in_hand[j]]
        w = live[0] if live else None
        pot = sum(self.contrib)
        if w is not None:
            self.stacks[w] += pot
        self.result = {
            "showdown": False, "winners": [w] if w is not None else [], "pot": pot,
            "payouts": [pot if j == w else 0 for j in range(self.n)],
            "pots": [{"amount": pot, "eligible": [w] if w is not None else [],
                      "winners": [{"seat": w, "amount": pot}] if w is not None else [],
                      "split": False}],
            "tie": False, "ranks": None}
        return self.result

    # ---------- 展示 ----------
    def state(self):
        return {
            "street": STREET_NAMES[self.street],
            "board": [c.code for c in self.board],
            "pot": self.pot,
            "stacks": list(self.stacks),
            "street_bet": list(self.street_bet),
            "to_act": self.to_act,
            "current_bet": self.current_bet,
            "holes": [[c.code for c in h] for h in self.holes],
            "folded": list(self.folded),
            "all_in": list(self.all_in),
            "in_hand": list(self.in_hand),
            "contrib": list(self.contrib),
        }

    def describe_result(self) -> str:
        """一句话结算（CLI 用）：多人时不写「平分」——只有真的被平分才那么说。"""
        if not self.result:
            return "未结束"
        ws = [w for w in self.result["winners"] if w is not None]
        if not ws:
            return "无人获胜"
        payouts = self.result.get("payouts") or []
        names = "、".join(f"P{w}" for w in ws)
        if len(ws) == 1:
            amt = payouts[ws[0]] if payouts else self.result["pot"]
            return f"{names} 赢得 {amt}"
        detail = "、".join(f"P{w} +{payouts[w]}" for w in ws) if payouts else names
        verb = "平分" if self.result.get("tie") else "分得"
        return f"{names} {verb}底池（{detail}）"


if __name__ == "__main__":
    # 自检: 随机对局 + 筹码守恒 (2/3/6 人各 1500 手)
    rng = random.Random(2026)
    for n in (2, 3, 6):
        total0 = 200 * n
        for h in range(1500):
            stacks = [200] * n
            g = Hand(stacks, button=h % n, rng=rng)
            guard = 0
            while g.to_act is not None and guard < 600:
                g.apply(rng.choice(g.legal_actions()))
                guard += 1
            assert sum(g.stacks) == total0, f"筹码不守恒(n={n}): {g.stacks}"
            assert g.result is not None, f"对局未结算(n={n})"
    print("筹码守恒 (2/3/6 人) 各 1500 手通过 ✓")

    # 边池专项: 三家全下不同筹码, 验证分层
    from .cards import Card as C
    def mk(code):
        return C(code)
    print("\n边池单元验证:")
    contrib = [200, 100, 50]
    in_hand = [True, True, True]
    pots = Hand.build_pots(contrib, in_hand)
    print("  contrib=[200,100,50] ->", pots)
    assert sum(a for _, a in pots) == 350, "边池总额 != 350"
    assert pots[0] == ([0, 1, 2], 150), pots[0]   # 主池 50*3
    assert pots[1] == ([0, 1], 100), pots[1]      # 边池 50*2
    assert pots[2] == ([0], 100), pots[2]         # 玩家0 未被跟的 100(自动收下)
    print("  分层正确 ✓")
