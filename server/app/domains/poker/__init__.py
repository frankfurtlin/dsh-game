"""德扑训练器 —— 纯逻辑包（不依赖 FastAPI / 数据库，可单独测试）。

本包是从 betterlife 原样搬进 dsh-game 插件的引擎，只留纯逻辑：
`cards` / `game` / `evaluator` / `equity` / `ai`，外加 `web.html`（牌桌前端）
与 `cli.py` / `sim_one_hand.py`（命令行入口）。

* HTTP 层在插件的 `server/app/api/routes/poker.py`，路由前缀 `/poker`
  （浏览器经 DSH 反代访问 `/game/poker/`；鉴权由 DSH 的 `/game` 闸门负责）；
* 模块间导入一律用**包内相对导入**（`from .cards import …`）—— `cards`/`game`/`ai`
  这些名字太通用，放进别的包容易撞名；
* 对局只存进程内存，重启即清。

用法与玩法见本目录 `README.md`。
"""