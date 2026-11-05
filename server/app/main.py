"""dsh-game — FastAPI 组合根（薄壳）。

只做三件事：

  1. 建 app、挂两个领域 router（poker / mahjong，路径前缀 `/poker`、`/mahjong`）；
  2. 给插件根路径 `/` 一个双入口小页（相对链接，DSH 下是 `/game/`，本机直连也行）；
  3. `/healthz` 供 systemd / 自测探活。

与 betterlife 不同，这里**没有**登录中间件、没有静态挂载、没有数据库：
鉴权由 DSH 的 `/game` 反代闸门负责；两个页面的 JS/CSS/图标全内联在 web.html，
后端只按页面路由返回 FileResponse。

启动（由 Lead 的 systemd 调用，WorkingDirectory 指向本插件的 server/）：

    /usr/bin/python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8817
"""
import os
import sys

# 让 `python -m app.main` 与 `python app/main.py` 都能跑：把 server/ 加进 sys.path。
_SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVER_ROOT not in sys.path:
    sys.path.insert(0, _SERVER_ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402

from app.api.routes import mahjong, poker  # noqa: E402

APP_NAME = "dsh-game"
APP_VERSION = "0.1.0"

# 关掉 /docs、/redoc、/openapi.json：插件只服务两个页面与它们的 XHR 接口，
# 多余的 schema 端点没有收益（未知路径统一 404 也是验收项之一）。
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(poker.router)
app.include_router(mahjong.router)

# 根路径双入口：全部相对链接，所以 DSH 下（/game/）与本机直连（/）都能用。
_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>dsh-game · 扑克 / 麻将</title>
<style>
  :root{color-scheme:light dark}
  body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
       background:color-mix(in srgb,currentColor 4%,transparent);color:inherit}
  .box{display:flex;flex-direction:column;gap:18px;max-width:440px;padding:36px;text-align:center}
  h1{margin:0;font-size:22px;letter-spacing:.5px}
  p{margin:0;font-size:14px;opacity:.7;line-height:1.6}
  .links{display:flex;gap:14px;justify-content:center;flex-wrap:wrap}
  a{display:block;padding:14px 26px;border-radius:12px;border:1px solid color-mix(in srgb,currentColor 20%,transparent);
    color:inherit;text-decoration:none;font-size:15px;font-weight:600;
    background:color-mix(in srgb,currentColor 6%,transparent)}
  a:hover{background:color-mix(in srgb,currentColor 12%,transparent)}
</style>
</head>
<body>
  <div class="box">
    <h1>♠️ 扑克 · 🀄 麻将</h1>
    <p>两个训练器各自独立开局，对局只存在内存里，重启即清。</p>
    <div class="links">
      <a href="poker/">德州扑克</a>
      <a href="mahjong/">四川麻将</a>
    </div>
  </div>
</body>
</html>
"""


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    """双入口小页（DSH 面板一般直接打开 /game/poker/ 或 /game/mahjong/）。"""
    return HTMLResponse(_INDEX_HTML)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """探活：systemd 与自测脚本都用它判断服务是否就绪。"""
    return {"ok": True, "app": APP_NAME, "version": APP_VERSION}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("DSH_GAME_PORT", "8817")),
    )
