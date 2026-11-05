# dsh-game

DSH Web 插件：把「德州扑克训练器」和「四川麻将训练器」接进 DSH 侧栏。两个游戏各自独立开局，对局只存在后端内存里（重启即清），不落库、不写文件。

- 侧栏「更多」菜单里多两行：**德州扑克**、**麻将**。点任一行都会关闭菜单并打开同一个主面板，面板自动切到对应 tab。
- 主面板是双 tab（扑克 / 麻将）+ 工具条（返回对话 / 刷新 / 新窗口打开），内容是同源 iframe。
- 浏览器只访问 DSH 自己的 `/game/...` 路径，由插件的 host 半反代到 `127.0.0.1:8817`；后端不直接暴露公网，也**没有**自己的登录逻辑，鉴权完全由 DSH 的登录/信任闸门负责。

## 架构

```
浏览器（DSH Web，3080）
  └─ /game/**  ──►  lib/index.js（host 半，Cordis）
                     · ctx.connection.requestRejection()：401 未登录 / 403 来源不可信
                     · /game → 302 /game/
                     · 剥掉 /game 前缀、补 x-forwarded-*、10s 超时 → 504 / 连不上 → 502
                     └─►  127.0.0.1:8817  FastAPI（server/app，由 systemd 常驻）
                            · GET /poker/、/poker/api/{new,state,action}
                            · GET /mahjong/、/mahjong/api/{new,state,action}
                            · 规则/评估/AI 全是 betterlife 原样复制的纯逻辑包
```

| 目录 | 内容 |
| --- | --- |
| `lib/index.js` | host 半：`/game` 反代 + DSH 鉴权闸门（prefix handler）。 |
| `client.js` | client 半：手写 `window.__ModuleLoader__` 工厂；main 座位 `key='dsh-game'` 双 tab 面板；`sidebar.panellist.actions` 两行菜单项。 |
| `server/app/main.py` | FastAPI 组合根：挂两个 router、根路径双入口小页、`/healthz`。 |
| `server/app/domains/poker/` | 德扑引擎（cards / game / evaluator / equity / ai）+ `web.html`。**原样复制，未改逻辑。** |
| `server/app/domains/mahjong/` | 麻将引擎（tiles / hand / game / ai）+ `web.html`。同上。 |
| `server/app/api/routes/` | HTTP 适配层（`/poker`、`/mahjong` 前缀）。 |
| `server/app/services/game_store.py` | 对局内存仓库（条数上限 + 取出刷新 LRU）。 |
| `verification/` | 三套验收脚本 + `shots/` 截图。 |
| `cordis.patch.yml` | bundle 补丁，`id` 必须等于包名 `dsh-game`。 |

## 启动后端

依赖系统 Python（本机已装 fastapi 0.142.2 / uvicorn 0.54.0），**不建 venv**：

```bash
cd /root/workspace/plugins/dsh-game/server
/usr/bin/python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8817
```

正式端口 `8817` 由 systemd 常驻（WorkingDirectory 指向本目录的 `server/`）；`8917` 是自测端口，验收脚本会自己拉起、跑完杀掉。只监听 `127.0.0.1`，从不监听 `0.0.0.0`。反代侧可用 `DSH_GAME_UPSTREAM_PORT` 覆盖上游端口（默认 8817）。

探活：`curl -s http://127.0.0.1:8817/healthz` → `{"ok":true,...}`。

## 验收

三套脚本都不需要装进 DSH 也能跑（脚本自己拉起/清理后端，需要 Playwright 时用本机已装的副本）：

```bash
cd /root/workspace/plugins/dsh-game
node verification/verify-app.mjs      # Playwright：真实点击两个游戏（19 项）
node verification/verify-host.mjs     # 反代 + 鉴权闸门（8 项）
node verification/verify-client.mjs   # 客户端注册形状 + 组件渲染（17 项）
```

2026-11-04 实测：**19 PASS / 0 FAIL**、**8 PASS / 0 FAIL**、**17 PASS / 0 FAIL**，全程无 console error。截图：

- `verification/shots/poker-table.png` —— 点「开始牌局」后：2 个座位、自己的底牌有牌面、5 个操作按钮。
- `verification/shots/mahjong-table.png` —— 点「开始牌局」→ 定缺 → 摸牌（14 张）→ 点推荐牌出牌后：手牌与牌桌渲染完整。

`verify-app.mjs` 覆盖的关键路径（每条都断言了真实 DOM 与 HTTP 状态）：

1. `/poker/`：点「开始牌局」→ `POST /poker/api/new` 200 → 牌桌可见、`#seats .seat` 2 个、自己底牌 `.cn` 有牌面、`#actions button` 出现；点「跟注」→ `POST /poker/api/action` 200。
2. `/mahjong/`：点「开始牌局」→ `POST /mahjong/api/new` 200 → 13 张手牌渲染；定缺 → action 200 → 14 张待打；点推荐牌 → action 200。
3. 两页 HTML 无 `/mine` 绝对路径残留；全程无 console error / pageerror。

`verify-host.mjs` 用假 `ctx.connection` 与临时端口 8898证明：放行时 `/game/poker/`、`/game/*/api/*` 正常剥前缀转发；401/403 在反代之前被挡；`/game` 302 到 `/game/`；未知路径透传 404；上游没起时 502。

`verify-client.mjs` 用 mock 的 `slots`/`layout` + 宿主 react 18 渲染组件，证明注册形状（main `key=dsh-game`、两行 action 的 id/order）、双 tab、iframe 地址、点菜单的顺序（先 `onDismiss` 再 `open` → `selectPanel('dsh-game')`）、切换 tab 后的 iframe，以及没有 primitives 时降级为原生按钮。

> **尚未在真实 DSH 里验收**：本机约定禁止我安装插件 / 改 `/root/.dsh`，所以「更多」菜单实际渲染与面板嵌入需要 Lead 安装后在浏览器里点一遍（重点是两行菜单项与 `/game/` 反代）。上面三套脚本保证的是插件自身逻辑正确；DSH 装载环节失败时，先看 `dsh` 日志里 `dsh-game` 的加载错误。

## 与 betterlife 的关系 / 改动范围

游戏规则、牌型评估、蒙特卡洛、AI、麻将向听/进张全部从 betterlife **原样复制**（`app/domains/poker/**`、`app/domains/mahjong/**`、`app/services/game_store.py`），不重写。改动只有：

1. 路由前缀：`/mine/poker` → `/poker`、`/mine/mahjong` → `/mahjong`；错误体沿用 FastAPI 默认 `{"detail": ...}`。
2. `web.html` 的 API 基址改相对路径（页面在 `/poker/`、`/mahjong/` 下），去掉 `/mine` 的 favicon 引用，改成内联 data URI。
3. 去掉 betterlife 的登录中间件/统一错误处理器依赖（鉴权交给 DSH 反代闸门）。

## 限制与风险

- **内存态**：两个游戏的对局都在 uvicorn 进程内存里，重启清空；多 worker 部署会丢对局（必须单 worker）。
- **反代超时 10s**：接口实测都在 1s 内，超长请求会得到 504；如需更长改 `lib/index.js` 的 `UPSTREAM_TIMEOUT_MS`。
- 只支持 HTTP 反代，没有 WebSocket；两个游戏都不用长连接。
- `/game` 是前缀匹配：后端新增路径会自动可用，但都要挂在 `/poker`、`/mahjong` 下才能被页面用到。
- 后端自身不做鉴权：**不要**把 8817 暴露到 `0.0.0.0` 或公网；对外只能走 DSH 的 `/game`。
- 目录里没有 `node_modules`：客户端只依赖宿主注入的 `react` 与（可选）`@deepseek-ai/dsh-client-ui-primitives`，缺失时自动降级。
