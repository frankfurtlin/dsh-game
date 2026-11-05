"""dsh-game — 德扑训练器 routes（路径前缀 /poker）。

来源：betterlife 的 `app/api/routes/poker.py`，本轮原样迁入独立 DSH 插件 dsh-game。
与 betterlife 版的差别只有三处，游戏规则/AI/权益计算完全没动：

  1. 路径前缀改成 `/poker`（betterlife 版前面还带项目前缀）；
  2. 去掉 betterlife 的登录中间件依赖 —— 鉴权由 DSH host 半的 `/game` 反代闸门负责；
  3. 错误体沿用 FastAPI 默认的 `{"detail": …}`（web.html 读的就是 detail）。

设计取舍（继承自 betterlife，未变）：

* **对局存内存**（`GAMES`，键是 12 位随机 hex）：状态机与蒙特卡洛都活在进程里，不落库。
  重启即清空 —— 训练器没有「续上上一局」的需求。
* **决策辅助在后端算**：equity（蒙特卡洛 4000 次）、底池赔率、跟注 EV、GTO 近似建议
  都由后端在轮到玩家时一并算好返回，避免前端再实现一份牌型评估。
* **AI 在请求内推进**：轮到 AI 时后端连续行动到轮回玩家或终局，过程写进 `ai_log`
  供前端回放。无后台任务、无轮询、无中间状态。
"""

import os
import random
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.domains.poker.cards import Card
from app.domains.poker.game import Hand, SHOWDOWN, STREET_NAMES
from app.domains.poker.equity import equity_vs_random, pot_odds, ev_call
from app.domains.poker.evaluator import evaluate_best, category_name
from app.domains.poker.ai import decide, STYLES
from app.services.game_store import GameStore

router = APIRouter()                       # 路径自带 /poker 前缀（不是 /api）
_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_POKER_DIR = os.path.join(_APP_DIR, "domains", "poker")

GAMES = GameStore(max_games=200)           # game_id -> {game, hero, ai, rng}
EQUITY_ITERS = 4000                        # 玩家决策辅助的蒙特卡洛精度（高）
AI_ITERS = 400                             # AI 决策精度（低：风格由权重驱动，精度不影响手感）

SEAT_NAMES = ["你", "AI-1", "AI-2", "AI-3", "AI-4", "AI-5"]


class ActionReq(BaseModel):
    action: str               # fold / check / call / raise
    amount: int = 0           # raise 时为本街总额


class NewReq(BaseModel):
    n_players: int = 2        # 2..6，含你本人
    ai_style: str = "loose_aggressive"
    stacks: int = 200


def _live_opponents(g, hero):
    """当前还活着的对手数（至少 1）：多人底池里 equity 必须按这个算，否则虚高。"""
    return max(1, sum(1 for j in range(g.n) if j != hero and g.in_hand[j]))


def snapshot(g, hero):
    """把一局状态 + 决策辅助 + 各座位视图打包给前端。"""
    me = hero
    to_call = max(0, g.current_bet - g.street_bet[me])
    equity_info = None
    advice = None
    if g.to_act == me and g.street != SHOWDOWN:
        n_opp = _live_opponents(g, me)
        eq = equity_vs_random(g.holes[me], g.board, iters=EQUITY_ITERS, n_opponents=n_opp)
        need = pot_odds(to_call, g.pot) if to_call else 0.0
        ev = ev_call(eq.equity, g.pot, to_call) if to_call else 0.0
        equity_info = {
            "equity": round(eq.equity, 4),
            "win": round(eq.win, 4),
            "tie": round(eq.tie, 4),
            "need": round(need, 4),
            "ev": round(ev, 2),
            "call_amount": to_call,
            "n_opponents": n_opp,
        }
        # decide 在翻牌后会再要一次 equity；这里把上面刚算好的 eq 直接给它，省掉一次
        # 重复的蒙特卡洛（六人桌约 190ms），而且 advice 用上了 4000 iters 的结果、更准。
        # 翻牌前 decide 走查表不调 equity_fn，所以这个闭包在那里根本不会被触发。
        def _reuse_equity(*_args, **_kwargs):
            return eq

        # mix=False: 建议面板必须**稳定** —— AI 实战是混合策略(会随机慢打/诈唬),
        # 但把随机建议显示给玩家会让人没法读, 所以这里只要确定性的"数学最优"。
        advice = repr(decide(g, me, _reuse_equity, style="gto_approx",
                             iters=EQUITY_ITERS, n_opponents=n_opp, mix=False))

    seats = []
    for i in range(g.n):
        seats.append({
            "idx": i,
            "name": SEAT_NAMES[i] if i < len(SEAT_NAMES) else f"P{i}",
            "is_hero": i == me,
            "stack": g.stacks[i],
            "contrib": g.contrib[i],
            "street_bet": g.street_bet[i],
            "folded": g.folded[i],
            "all_in": g.all_in[i],
            "in_hand": g.in_hand[i],
            "is_button": i == g.button,
            "to_act": g.to_act == i,
            "last_action": repr(g.last_action[i]) if g.last_action[i] else None,
            "hole": ([c.code for c in g.holes[i]]
                     if (i == me or (g.result and g.in_hand[i])) else None),
        })

    # 玩家当前成牌牌型（至少 5 张可评估时）
    hand_strength = None
    my_cards = g.holes[me] + g.board
    if len(my_cards) >= 5:
        hand_strength = category_name(evaluate_best(my_cards))

    raise_opts = [a.amount for a in g.legal_actions() if a.kind == "raise"] if g.to_act == me else []
    return {
        "game_id": g._gid,
        "n": g.n,
        "street": STREET_NAMES[g.street],
        "street_key": g.street,
        "board": [c.code for c in g.board],
        "pot": g.pot,
        "current_bet": g.current_bet,
        "to_act": g.to_act,
        "you_to_act": g.to_act == me,
        "hero_hole": [c.code for c in g.holes[me]],
        "folded": list(g.folded),
        "all_in": list(g.all_in),
        "button": g.button,
        "seats": seats,
        "legal": [{"kind": a.kind, "amount": a.amount, "is_allin": a.is_allin}
                  for a in g.legal_actions()],
        "equity": equity_info,
        "advice": advice,
        "hand_strength": hand_strength,
        "result": g.result,
        "raise_min": min(raise_opts) if raise_opts else None,
        "raise_max": max(raise_opts) if raise_opts else None,
        "you_stack": g.stacks[me],
        "ai_style": GAMES[g._gid]["ai"] if hasattr(g, "_gid") and g._gid in GAMES else None,
    }


def _step_ai(g, hero, style, rng=None):
    """从当前状态推进，直到轮到玩家或终局。记录过程供前端回放。

    rng 传对局的随机源：AI 已是混合策略（会随机慢打/诈唬），把同一局的 rng 串起来
    才能复现"这手牌 AI 为什么这么打"。
    """
    steps = 0
    log = []
    while g.to_act is not None and g.to_act != hero and steps < 400:
        idx = g.to_act
        n_opp = _live_opponents(g, idx)
        a = decide(g, idx, equity_vs_random, style=style, iters=AI_ITERS,
                   n_opponents=n_opp, rng=rng)
        g.apply(a)
        log.append({"seat": idx, "name": SEAT_NAMES[idx], "action": repr(a), "street": g.street})
        steps += 1
    return log


@router.get("/poker", include_in_schema=False)
@router.get("/poker/", include_in_schema=False)
def poker_index():
    """牌桌页面（无尾斜杠也直接返回）。"""
    return FileResponse(os.path.join(_POKER_DIR, "web.html"))


@router.post("/poker/api/new")
def new_game(req: NewReq):
    n = max(2, min(6, req.n_players))
    if req.ai_style not in STYLES:
        req.ai_style = "loose_aggressive"
    gid = uuid.uuid4().hex[:12]
    rng = random.Random()
    g = Hand([req.stacks] * n, button=0, rng=rng)
    g._gid = gid
    GAMES.remember(gid, {"game": g, "hero": 0, "ai": req.ai_style, "rng": rng})
    log = _step_ai(g, 0, req.ai_style, rng)
    snap = snapshot(g, 0)
    snap["ai_log"] = log
    return snap


@router.get("/poker/api/state/{gid}")
def get_state(gid: str):
    rec = GAMES.recall(gid)
    if not rec:
        raise HTTPException(404, "对局不存在或已结束回收")
    return snapshot(rec["game"], rec["hero"])


@router.post("/poker/api/action/{gid}")
def do_action(gid: str, req: ActionReq):
    rec = GAMES.recall(gid)
    if not rec:
        raise HTTPException(404, "对局不存在")
    g = rec["game"]
    me = rec["hero"]
    if g.to_act != me:
        raise HTTPException(400, "现在不是你的回合")
    legal = g.legal_actions()
    chosen = None
    for a in legal:
        if a.kind == req.action:
            if req.action == "raise":
                if a.amount == req.amount:
                    chosen = a
                    break
            else:
                chosen = a
                break
    if chosen is None:
        raise HTTPException(400, f"非法动作 {req.action} {req.amount} / 合法: {legal}")
    g.apply(chosen)
    log = _step_ai(g, me, rec["ai"], rec.get("rng"))
    snap = snapshot(g, me)
    snap["ai_log"] = log
    return snap


# 冷启动预热：equity 的蒙特卡洛首次调用要建表/导入，预热一次让第一局不卡。
# 原实现在 web.py 里用 @app.on_event("startup")；这里是路由模块，没有 app 对象，
# 改成 import 期执行。代价是模块导入慢几十毫秒（只在启动时发生一次）。
equity_vs_random([Card("As"), Card("Ks")], [], iters=200)
