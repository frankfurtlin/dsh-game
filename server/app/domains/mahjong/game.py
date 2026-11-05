"""对局状态机 —— 定缺 / 摸打 / 碰杠胡 / **血战到底**。

结构对照 `poker/game.py`：`Game` 持有全部状态，`legal_actions()` 给出当前
等待玩家的合法动作，`apply()` 落地并推进。人类只有一个（0 号位），其余由 `ai.py` 驱动。

川麻的关键规则都在这里：
- **定缺**：开局每人定一门"缺"，缺门牌必须先打完才能打别门，胡牌时手里不能有缺门牌。
- **不能吃**：只有碰、杠、胡。
- **血战到底**：有人胡牌后**其余家继续打**，直到只剩一家没胡或牌墙摸完。
  已胡的玩家不再摸打、也不能再碰杠，但仍参与结算。

v1 明确不做（同时记在 `__init__.py`）：查大叫 / 花猪 / 刮风下雨、抢杠胡、
杠上开花、呼叫转移、换三张，以及**一炮多响**（一张打牌只判给优先级最高的那家胡）。
"""
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .hand import advise, is_win, legal_discards, win_types
from .tiles import (N_KINDS, SUIT_NAMES, SUITS, TILES_PER_KIND, make_wall,
                    suit_of, tile_at)

PHASE_VOID = "void"          # 定缺
PHASE_PLAY = "play"
PHASE_OVER = "over"

# 番型 → 倍数（简化，够表达川麻的牌型差距）。取多个番型里最大的那个。
FAN_MULTIPLIER = {
    "平胡": 1, "对对胡": 2, "金钩钓": 2,
    "七对": 4, "清一色": 4, "龙七对": 8,
}
ACTION_NAMES = {"discard": "打", "pong": "碰", "kong": "杠",
                "hu": "胡", "pass": "过", "void": "定缺"}


@dataclass
class Meld:
    """亮出的面子。"""
    kind: str                 # pong / kong(明杠) / ankong(暗杠) / bukong(补杠)
    tile: int
    from_player: int = -1

    @property
    def code(self) -> str:
        return tile_at(self.tile).code


@dataclass
class Action:
    kind: str                 # discard / pong / kong / hu / pass / void
    tile: int = -1
    suit: str = ""            # 仅 "void" 用

    def __repr__(self) -> str:
        if self.kind == "void":
            return f"定缺{SUIT_NAMES.get(self.suit, '')}"
        name = ACTION_NAMES.get(self.kind, self.kind)
        return name if self.tile < 0 else f"{name}{tile_at(self.tile).name}"


class Player:
    def __init__(self, idx: int):
        self.idx = idx
        self.hand = [0] * N_KINDS
        self.melds: List[Meld] = []
        self.discards: List[int] = []
        self.void: Optional[str] = None
        self.hu = False
        self.hu_info: Optional[Dict] = None
        self.score = 0

    @property
    def n_melds(self) -> int:
        return len(self.melds)

    @property
    def active(self) -> bool:
        """还在打。血战到底里胡了的就不再摸打。"""
        return not self.hu

    def hand_tiles(self) -> List[int]:
        return [i for i in range(N_KINDS) for _ in range(self.hand[i])]

    def exposed_suits(self) -> List[str]:
        return [suit_of(m.tile) for m in self.melds]

    def snapshot(self, reveal: bool = True) -> Dict:
        d = {
            "idx": self.idx,
            "melds": [{"kind": m.kind, "tile": m.code} for m in self.melds],
            "discards": [tile_at(i).code for i in self.discards],
            "void": self.void,
            "hu": self.hu,
            "hu_info": self.hu_info,
            "score": self.score,
            "hand_count": sum(self.hand),
        }
        if reveal:
            d["hand"] = [tile_at(i).code for i in self.hand_tiles()]
        return d


class Game:
    """一局川麻（4 人）。人类固定是 0 号位。"""

    def __init__(self, human: int = 0, rng: Optional[random.Random] = None,
                 dealer: int = 0):
        self.rng = rng or random.Random()
        self.human = human
        self.dealer = dealer
        self.wall = make_wall()
        self.rng.shuffle(self.wall)
        self.players = [Player(i) for i in range(4)]
        self.phase = PHASE_VOID
        self.turn = dealer
        self.waiting: Optional[Tuple[str, int]] = None
        self.pending: Optional[Dict] = None
        self.log: List[Dict] = []
        self.result: Optional[Dict] = None
        self.last_draw: Optional[int] = None
        for _ in range(13):                      # 发牌：每人 13 张
            for p in self.players:
                p.hand[self._draw_idx()] += 1
        self._refresh()

    # ---------- 基础 ----------
    def _draw_idx(self) -> int:
        if not self.wall:
            raise IndexError("牌墙已摸完")
        return self.wall.pop().idx

    def _say(self, player: int, text: str, kind: str = "") -> None:
        self.log.append({"player": player, "action": text, "kind": kind})

    @property
    def over(self) -> bool:
        return self.phase == PHASE_OVER

    def _alive(self) -> List[Player]:
        return [p for p in self.players if p.active]

    def _refresh(self) -> None:
        """重算"现在等谁"。"""
        if self.phase == PHASE_OVER:
            self.waiting = None
            return
        if self.phase == PHASE_VOID:
            nxt = next((p for p in self.players if p.void is None), None)
            if nxt is not None:
                self.waiting = ("void", nxt.idx)
                return
            self.phase = PHASE_PLAY
            # 定缺结束 → 庄家摸第一张。
            # 少了这一下，庄家只有 13 张就被要求打牌，而且此后**永久少一张**
            # （其余三家都是「摸完再打」），等于庄家整局都胡不了。
            # 这里只会执行一次：phase 已经改成 PLAY，下次进来不再进这个分支
            # —— `_refresh()` 被 `advance()` 每轮调用，必须保持幂等。
            if self.wall:
                self.last_draw = self._draw_idx()
                dp = self.players[self.turn]
                dp.hand[self.last_draw] += 1
                self._say(dp.idx, "摸牌", "draw")
        if self.pending is not None:
            self.waiting = ("react", self.pending["actor"])
            return
        self.waiting = ("act", self.turn)

    # ---------- 合法动作 ----------
    def legal_actions(self) -> List[Action]:
        if self.over or self.waiting is None:
            return []
        who, idx = self.waiting
        p = self.players[idx]
        if who == "void":
            return [Action("void", -1, s) for s in SUITS]
        if who == "react":
            return self._react_options(p, self.pending["tile"], self.pending["from"])
        return self._act_options(p)

    def _act_options(self, p: Player) -> List[Action]:
        """轮到 p、刚摸完牌（或碰完）的选择。"""
        out: List[Action] = []
        if self.last_draw is not None and is_win(p.hand, p.n_melds, p.void):
            out.append(Action("hu"))                       # 自摸
        for i in range(N_KINDS):
            if p.hand[i] == 4:
                out.append(Action("kong", i))              # 暗杠
        for m in p.melds:
            if m.kind == "pong" and p.hand[m.tile] >= 1:
                out.append(Action("kong", m.tile))         # 补杠
        for i in legal_discards(p.hand, p.void):
            out.append(Action("discard", i))
        return out

    def _react_options(self, p: Player, t: int, frm: int) -> List[Action]:
        """别人打出 t 之后，p 能做什么。"""
        if p.hu or p.idx == frm:
            return []
        out: List[Action] = []
        probe = list(p.hand)
        probe[t] += 1
        if is_win(probe, p.n_melds, p.void):
            out.append(Action("hu", t))
        # 缺门牌不碰不杠（留着只会拖慢自己）
        if p.void is None or suit_of(t) != p.void:
            if p.hand[t] >= 3:
                out.append(Action("kong", t))
            if p.hand[t] >= 2:
                out.append(Action("pong", t))
        out.append(Action("pass"))
        return out

    def _can_react(self, p: Player, t: int, frm: int) -> bool:
        return len(self._react_options(p, t, frm)) > 1        # 除 pass 外还有别的

    # ---------- 落地 ----------
    def choose_void(self, player: int, suit: str) -> None:
        assert self.phase == PHASE_VOID and suit in SUITS, "不在定缺阶段"
        self.players[player].void = suit
        self._say(player, f"定缺{SUIT_NAMES[suit]}", "void")
        self._refresh()

    def apply(self, action: Action) -> None:
        """对当前等待者落地一个动作，然后自动推进。"""
        self._apply_internal(action)
        self.advance()

    def _apply_internal(self, action: Action) -> None:
        """只落地，不推进。

        必须和 `advance()` 分开：`advance()` 内部也要落地 AI 的动作，
        如果它直接调 `apply()` 就会 `apply → advance → apply` 无限互相递归
        （第一版就是这么把栈跑爆的）。
        """
        if self.over or self.waiting is None:
            return
        who, idx = self.waiting
        p = self.players[idx]
        if who == "void":
            self.choose_void(idx, action.suit)
        elif who == "react":
            self._apply_react(p, action)
        else:
            self._apply_turn(p, action)

    def _apply_turn(self, p: Player, a: Action) -> None:
        if a.kind == "hu":
            self._declare_hu(p, "自摸", from_player=p.idx)
            if not self.over:
                self._next_turn()          # 胡完必须换人，否则会一直被问同一个玩家
        elif a.kind == "kong":
            self._do_kong(p, a.tile, from_player=p.idx)
        elif a.kind == "discard":
            self._do_discard(p, a.tile)

    def _apply_react(self, p: Player, a: Action) -> None:
        t, frm = self.pending["tile"], self.pending["from"]
        if a.kind == "pass":
            self.pending["remaining"].discard(p.idx)
            if self.pending["remaining"]:
                self.pending["actor"] = self._next_reactor()
                self._refresh()
            else:
                self.pending = None
                self._next_turn()
            return
        # 有人真做了动作，其余家就没机会了（v1 不支持一炮多响）
        self.pending = None
        if a.kind == "hu":
            self._declare_hu(p, "点炮", from_player=frm, tile=t)
            if not self.over:
                self._next_turn()          # 同上：胡完必须换人
        elif a.kind == "kong":
            self._do_kong(p, t, from_player=frm)
        elif a.kind == "pong":
            self._do_pong(p, t, from_player=frm)

    def _do_discard(self, p: Player, t: int) -> None:
        p.hand[t] -= 1
        p.discards.append(t)
        self.last_draw = None
        self._say(p.idx, f"打 {tile_at(t).name}", "discard")
        reactors = [q.idx for q in self.players if self._can_react(q, t, p.idx)]
        if reactors:
            self.pending = {"tile": t, "from": p.idx,
                            "remaining": set(reactors), "actor": -1}
            self.pending["actor"] = self._next_reactor()
            self._refresh()
        else:
            self._next_turn()

    def _next_reactor(self) -> int:
        rem = self.pending["remaining"]
        if not rem:
            return -1
        # 人类优先，否则 AI 会先把牌碰掉、玩家永远没机会做选择
        return self.human if self.human in rem else min(rem)

    def _do_pong(self, p: Player, t: int, from_player: int) -> None:
        p.hand[t] -= 2
        p.melds.append(Meld("pong", t, from_player))
        self._take_discard(from_player)
        self._say(p.idx, f"碰 {tile_at(t).name}", "pong")
        self.turn = p.idx
        self.last_draw = None
        self._refresh()

    def _do_kong(self, p: Player, t: int, from_player: int) -> None:
        if from_player != p.idx:                        # 明杠：杠别人打出的牌
            p.hand[t] -= 3
            m = Meld("kong", t, from_player)
            self._take_discard(from_player)
        elif p.hand[t] == 4:                            # 暗杠
            p.hand[t] -= 4
            m = Meld("ankong", t, p.idx)
        else:                                           # 补杠：已碰过，手里第 4 张
            p.hand[t] -= 1
            m = Meld("bukong", t, p.idx)
            for k, old in enumerate(p.melds):
                if old.kind == "pong" and old.tile == t:
                    p.melds.pop(k)
                    break
        p.melds.append(m)
        self._say(p.idx, f"{'暗杠' if m.kind == 'ankong' else '杠'} {tile_at(t).name}", "kong")
        self.turn = p.idx
        self.last_draw = None
        if self.wall:                                   # 杠了补一张
            self.last_draw = self._draw_idx()
            p.hand[self.last_draw] += 1
        self._refresh()

    def _take_discard(self, who: int) -> None:
        """被碰/杠/胡走的那张牌从对方河里拿走（显示上更贴近真实牌桌）。"""
        d = self.players[who].discards
        if d:
            d.pop()

    def _declare_hu(self, p: Player, how: str, from_player: int,
                    tile: Optional[int] = None) -> None:
        if tile is not None:
            p.hand[tile] += 1
            self._take_discard(from_player)
        types = win_types(p.hand, p.n_melds, p.void, p.exposed_suits())
        mult = max([FAN_MULTIPLIER.get(t, 1) for t in types] or [1])
        if how == "自摸":
            mult *= 2
        p.hu = True
        p.hu_info = {"how": how, "types": types, "fan": mult,
                     "from": None if how == "自摸" else from_player}
        shown = tile_at(tile).name if tile is not None else ""
        self._say(p.idx, f"{how} {shown}（{'/'.join(types)} ×{mult}）", "hu")
        self._settle(p, from_player, mult)
        self.pending = None
        # 自摸从赢家下家继续；点炮从放炮的下家继续（牌是他打的）
        self.turn = p.idx if how == "自摸" else from_player
        if len(self._alive()) <= 1:                     # 血战到底：只剩一家就收
            self._finish()

    def _settle(self, winner: Player, from_player: int, mult: int) -> None:
        """自摸每家赔；点炮只由放炮那家赔（v1 简化，已胡的也照赔）。"""
        if from_player == winner.idx:
            for q in self.players:
                if q.idx != winner.idx:
                    q.score -= mult
                    winner.score += mult
        else:
            self.players[from_player].score -= mult
            winner.score += mult

    # ---------- 推进 ----------
    def _next_turn(self) -> None:
        """轮到下一个还在打的人并让他摸牌。"""
        if not self.wall:
            self._finish()
            return
        for _ in range(4):
            self.turn = (self.turn + 1) % 4
            if self.players[self.turn].active:
                break
        else:
            self._finish()
            return
        p = self.players[self.turn]
        self.last_draw = self._draw_idx()
        p.hand[self.last_draw] += 1
        self._say(p.idx, "摸牌", "draw")
        self._refresh()

    def _finish(self) -> None:
        self.phase = PHASE_OVER
        self.pending = None
        self.result = {
            "reason": "血战结束" if any(p.hu for p in self.players) else "流局（牌墙摸完）",
            "winners": [p.idx for p in self.players if p.hu],
            "scores": [p.score for p in self.players],
        }
        self._say(-1, self.result["reason"], "over")
        self._refresh()

    def advance(self) -> None:
        """把 AI 的回合跑掉，直到需要人类输入或终局。"""
        from .ai import choose
        guard = 0
        while not self.over and guard < 600:
            guard += 1
            if self.phase == PHASE_VOID:
                for p in self.players:
                    if p.void is None and p.idx != self.human:
                        p.void = self._ai_void(p)
                        self._say(p.idx, f"定缺{SUIT_NAMES[p.void]}", "void")
            # 每轮都重算 waiting，绝不读可能过期的值。
            # 第一版只在 waiting is None 时才重算，结果"胡牌"改了状态却没刷新 waiting，
            # 同一个玩家被反复问、反复胡 —— 死循环且分数被反复结算。
            self._refresh()
            if self.waiting is None:
                return
            who, idx = self.waiting
            if who == "void" and idx == self.human:
                return                                    # 等玩家定缺
            if idx == self.human:
                return                                    # 等玩家行动
            opts = self.legal_actions()
            if not opts:
                self._next_turn()                         # 兜底，避免卡死
                continue
            self._apply_internal(choose(self, idx, opts))

    def _ai_void(self, p: Player) -> str:
        """定缺：选手里张数最少的那门（并列随机）。"""
        counts = {s: sum(p.hand[i] for i in range(N_KINDS) if suit_of(i) == s)
                  for s in SUITS}
        fewest = min(counts.values())
        return self.rng.choice([s for s, n in counts.items() if n == fewest])

    # ---------- 对外快照 ----------
    def _left_counts(self, me: int) -> List[int]:
        """牌墙里各牌种还剩几张 —— 扣掉所有河里的明牌、亮出的面子、以及自己手里的。

        这是进张枚数的分母，直接影响"打哪张"的排序，所以口径要说清：
        别人手里握着的牌**不扣**（那属于未知信息，扣了就成作弊了）。
        """
        left = [TILES_PER_KIND] * N_KINDS
        for q in self.players:
            for i in q.discards:
                left[i] -= 1
            for m in q.melds:
                left[m.tile] -= 4 if m.kind == "ankong" else 3
            if q.idx == me:
                for i in range(N_KINDS):
                    left[i] -= q.hand[i]
        return [max(0, n) for n in left]

    def snapshot(self, me: Optional[int] = None) -> Dict:
        me = self.human if me is None else me
        p = self.players[me]
        waiting = self.waiting
        my_turn = bool(waiting and waiting[1] == me)
        data = {
            "players": [q.snapshot(reveal=(q.idx == me or q.hu or self.over))
                        for q in self.players],
            "me": me,
            "wall_left": len(self.wall),
            "phase": self.phase,
            "turn": self.turn,
            "waiting": list(waiting) if waiting else None,
            "my_turn": my_turn,
            "need_void": bool(waiting and waiting[0] == "void" and waiting[1] == me),
            "log": self.log[-40:],
            "result": self.result,
            "legal": ([{"kind": a.kind,
                        "tile": tile_at(a.tile).code if a.tile >= 0 else None,
                        "suit": a.suit or None}
                       for a in self.legal_actions()] if my_turn else []),
        }
        data["advice"] = advise(p.hand, p.n_melds, p.void, left=self._left_counts(me))
        return data


def new_game(seed: Optional[int] = None, human: int = 0) -> Game:
    return Game(human=human, rng=random.Random(seed))
