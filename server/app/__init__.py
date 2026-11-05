"""dsh-game 的后端 FastAPI 应用。

从 betterlife 拆出来的「德州扑克 + 麻将」训练器后端：
  · `domains/poker/`、`domains/mahjong/` 是**原样复制**的纯逻辑包（规则/评估/AI 不动）；
  · `api/routes/poker.py`、`api/routes/mahjong.py` 是 HTTP 适配层，路径前缀改成
    `/poker` 与 `/mahjong`（betterlife 里前面还带项目前缀）；
  · `services/game_store.py` 是对局内存仓库（无数据库、重启即清）。

鉴权不在这里做：DSH host 半的 `/game` 反代会先过 DSH 的登录/信任围栏，
本进程只监听 127.0.0.1，不直接对公网。
"""
