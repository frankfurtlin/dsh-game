"""dsh-game — 川麻训练器路由：页面 + 三个接口（new / state / action）。

来源：betterlife 的 `app/api/routes/mahjong.py`，原样迁入独立 DSH 插件 dsh-game。
与 betterlife 版的差别：路径前缀改成 `/mahjong`，并去掉对 betterlife
登录中间件的假设 —— 鉴权由 DSH host 半的 `/game` 反代闸门负责。

错误一律 `raise HTTPException`，前端同时兼容 `{"detail": …}` 与 `{"ok":false,"error":…}`。

对局只存在内存里（重启即清），不做持久化：一局麻将几百个动作，落库没有收益，
而且和 poker 一样，"训练器"不需要回放历史。
"""

import os
import random
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.domains.mahjong.game import Action, Game
from app.domains.mahjong.tiles import SUIT_NAMES, parse
from app.services.game_store import GameStore

router = APIRouter()                    # 路径自带 /mahjong 前缀
_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MAHJONG_DIR = os.path.join(_APP_DIR, "domains", "mahjong")

GAMES = GameStore(max_games=100)        # game_id -> {"game": Game}
HUMAN = 0                               # 人类固定 0 号位（和 game.py 一致）


def _load(gid) -> Game:
    rec = GAMES.recall(gid)
    if rec is None:
        raise HTTPException(status_code=404, detail="牌局不存在或已过期，请重新开局")
    return rec["game"]


def _tile_idx(code: Optional[str]) -> int:
    if not code:
        raise HTTPException(status_code=400, detail="缺少牌参数")
    try:
        return parse(code).idx
    except (ValueError, IndexError, KeyError):
        raise HTTPException(status_code=400, detail=f"无法识别的牌：{code}")


class NewReq(BaseModel):
    seed: Optional[int] = None


class ActionReq(BaseModel):
    action: str
    tile: Optional[str] = None          # discard / pong / kong 用
    suit: Optional[str] = None          # void（定缺）用


@router.get("/mahjong", include_in_schema=False)
@router.get("/mahjong/", include_in_schema=False)
def mahjong_index():
    """牌桌页面（无尾斜杠也直接返回）。"""
    return FileResponse(os.path.join(_MAHJONG_DIR, "web.html"))


@router.post("/mahjong/api/new")
def new_game(req: Optional[NewReq] = None):
    gid = uuid.uuid4().hex[:12]
    g = Game(human=HUMAN, rng=random.Random(None if req is None else req.seed))
    GAMES.remember(gid, {"game": g})
    g.advance()                          # 把 AI 的定缺跑掉，停在玩家定缺/摸打
    return {"ok": True, "game_id": gid, "state": g.snapshot(HUMAN)}


@router.get("/mahjong/api/state/{gid}")
def get_state(gid: str):
    g = _load(gid)
    return {"ok": True, "state": g.snapshot(HUMAN)}


@router.post("/mahjong/api/action/{gid}")
def do_action(gid: str, req: ActionReq):
    g = _load(gid)
    if g.over:
        raise HTTPException(status_code=400, detail="这一局已经结束了，请重新开局")
    if g.waiting is None:
        raise HTTPException(status_code=400, detail="现在不该你行动")

    legal = g.legal_actions()
    kind = req.action

    if kind == "void":
        suit = (req.suit or "").lower()
        if suit not in SUIT_NAMES:
            raise HTTPException(status_code=400, detail="定缺必须是 万/条/筒 之一")
        if g.waiting[0] != "void":
            raise HTTPException(status_code=400, detail="现在已经不能改定缺了")
        g.apply(Action("void", -1, suit))
    elif kind == "pass":
        if not any(a.kind == "pass" for a in legal):
            raise HTTPException(status_code=400, detail="现在没有可过的动作")
        g.apply(Action("pass"))
    elif kind == "hu":
        if not any(a.kind == "hu" for a in legal):
            raise HTTPException(status_code=400, detail="现在还不能胡")
        g.apply(Action("hu"))
    elif kind in ("discard", "pong", "kong"):
        idx = _tile_idx(req.tile)
        match = next((a for a in legal if a.kind == kind and a.tile == idx), None)
        if match is None:
            raise HTTPException(status_code=400, detail="这个动作现在不合法")
        g.apply(match)
    else:
        raise HTTPException(status_code=400, detail=f"未知动作：{kind}")

    return {"ok": True, "state": g.snapshot(HUMAN)}
