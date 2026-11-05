/**
 * dsh-game —— host 半：把本地游戏后端（FastAPI，127.0.0.1:8817）挂到 DSH Web 的
 * `/game` 前缀下，并复用 DSH 自己的登录闸门。
 *
 * 设计要点（骨架照抄 dsh-ziwei 的反代，改动只有「剥 /game 前缀」与文案）：
 *  - 只在 127.0.0.1 上反代，不碰公网；上游端口默认 8817，可用
 *    `DSH_GAME_UPSTREAM_PORT` 覆盖（自测指向 8917 时用）。
 *  - 每个请求先过 `ctx.connection.requestRejection()`：403（Host/Origin 不在信任
 *    围栏内）/ 401（未登录）/ undefined（放行）。内嵌面板天然继承 DSH 的
 *    token/cookie 会话，后端因此不需要任何登录中间件。
 *  - `/game`（无尾斜杠）302 到 `/game/`：应用内部全用相对路径，缺尾斜杠会解析到
 *    错误的上一级。
 *  - 转发前剥掉 `/game` 前缀：上游 FastAPI 的路由是 `/poker/` 与 `/mahjong/`，
 *    不知道 DSH 给它套了一层前缀。上游若回以 `/` 开头的 Location，再补回前缀。
 *  - 剥 hop-by-hop 头、补 x-forwarded-*、10s 超时 → 504、ECONNREFUSED → 502、
 *    客户端断开时 destroy 上游请求。
 */
import { request as httpRequest } from 'node:http'

/** DSH Web 里挂载应用的前缀。 */
const ROUTE_PATH = '/game'
const UPSTREAM_HOST = '127.0.0.1'
const UPSTREAM_PORT = Number(process.env.DSH_GAME_UPSTREAM_PORT || 8817)
/** 反代上游的超时（毫秒）：两个训练器的接口都在 1s 内，10s 足够。 */
const UPSTREAM_TIMEOUT_MS = 10_000
const LOG_PREFIX = '[dsh-game]'

/** RFC 7230 hop-by-hop 头，不该被代理透传。 */
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
])

/** 转发给上游的请求头：剥掉逐跳头，补上 X-Forwarded-*。 */
function upstreamHeaders(req) {
  const out = {}
  for (const [key, value] of Object.entries(req.headers)) {
    if (value === undefined) continue
    if (HOP_BY_HOP.has(key.toLowerCase())) continue
    out[key] = value
  }
  out.host = `${UPSTREAM_HOST}:${UPSTREAM_PORT}`
  out['x-forwarded-host'] = req.headers.host || `${UPSTREAM_HOST}:${UPSTREAM_PORT}`
  out['x-forwarded-proto'] = 'http'
  out['x-forwarded-prefix'] = ROUTE_PATH
  if (req.socket && req.socket.remoteAddress) {
    out['x-forwarded-for'] = req.socket.remoteAddress
  }
  return out
}

/**
 * 上游响应头：剥掉逐跳头，交给 node 自己算 Transfer-Encoding；
 * 相对 Location 补回 `/game` 前缀，避免浏览器跳出反代前缀。
 */
function downstreamHeaders(upstreamRes) {
  const out = {}
  for (const [key, value] of Object.entries(upstreamRes.headers)) {
    if (value === undefined) continue
    if (HOP_BY_HOP.has(key.toLowerCase())) continue
    out[key] = value
  }
  const location = out.location
  if (
    typeof location === 'string' &&
    location.startsWith('/') &&
    !location.startsWith('//') &&
    !location.startsWith(`${ROUTE_PATH}/`) &&
    location !== ROUTE_PATH
  ) {
    out.location = `${ROUTE_PATH}${location}`
  }
  return out
}

function sendPlain(res, status, text) {
  if (res.headersSent) {
    res.end()
    return
  }
  res.writeHead(status, {
    'content-type': 'text/plain; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(text)
}

/** 鉴权闸门：没登录/主机不可信就直接挡掉，绝不把本地游戏服务暴露出去。 */
function rejectUnprivileged(ctx, req, res) {
  let rejection
  try {
    const connection = ctx.get('connection', false)
    rejection = connection && typeof connection.requestRejection === 'function'
      ? connection.requestRejection(req)
      : 401
  } catch {
    rejection = 401
  }
  if (!rejection) return false
  const text = rejection === 403
    ? 'dsh web: 该请求的主机/来源不在信任列表内。\n'
    : 'dsh web authentication required; reopen the URL printed by dsh web.\n'
  sendPlain(res, rejection, text)
  return true
}

/**
 * `/game/...` → 上游路径：去掉 `/game` 前缀，保留查询串。
 *
 * 例：`/game` → `/`；`/game/poker/` → `/poker/`；
 *     `/game/poker/api/action/abc?x=1` → `/poker/api/action/abc?x=1`。
 */
function upstreamPath(rawUrl) {
  const raw = String(rawUrl || '')
  const cut = raw.indexOf('?')
  const pathname = cut === -1 ? raw : raw.slice(0, cut)
  const search = cut === -1 ? '' : raw.slice(cut)
  let rest = pathname.startsWith(ROUTE_PATH) ? pathname.slice(ROUTE_PATH.length) : '/'
  if (!rest.startsWith('/')) rest = `/${rest}`
  if (rest === '') rest = '/'
  return rest + search
}

/** `/game` 前缀 → 上游 127.0.0.1:8817 的流式反代。 */
export function createHandler(ctx) {
  return function gameProxy(req, res) {
    if (rejectUnprivileged(ctx, req, res)) return

    const rawUrl = String(req.url || '')
    const pathname = rawUrl.split('?')[0]
    // 无尾斜杠的 /game（可带查询串）→ 302 到 /game/
    if (pathname === ROUTE_PATH) {
      const query = rawUrl.slice(pathname.length)
      res.writeHead(302, { location: `${ROUTE_PATH}/${query}`, 'cache-control': 'no-store' })
      res.end()
      return
    }

    const upstream = httpRequest(
      {
        host: UPSTREAM_HOST,
        port: UPSTREAM_PORT,
        method: req.method,
        // 传给上游的是剥掉 /game 之后的路径。
        path: upstreamPath(rawUrl),
        headers: upstreamHeaders(req),
      },
      (upstreamRes) => {
        res.writeHead(upstreamRes.statusCode || 502, downstreamHeaders(upstreamRes))
        upstreamRes.pipe(res)
        upstreamRes.on('error', () => res.destroy())
      },
    )

    // 上游卡住（不响应）时不能把 handler 永久挂起：超时直接 504。
    upstream.setTimeout(UPSTREAM_TIMEOUT_MS, () => {
      upstream.destroy(Object.assign(new Error('上游响应超时'), { code: 'ETIMEDOUT' }))
    })

    upstream.on('error', (error) => {
      if (error && error.code === 'ETIMEDOUT') {
        console.warn(`${LOG_PREFIX} 反代超时（10s）: ${req.method} ${req.url}`)
        sendPlain(res, 504, '游戏服务响应超时，请稍后重试。\n')
        return
      }
      const reason = error && error.code ? error.code : 'ECONNREFUSED'
      // 诊断信息只写宿主日志：回给浏览器的文案不带错误码、路径。
      console.warn(
        `${LOG_PREFIX} 反代失败（${reason}）: ${req.method} ${req.url} → 127.0.0.1:${UPSTREAM_PORT}`,
      )
      sendPlain(res, 502, '游戏服务暂时不可用（dsh-game 后端未启动？），请稍后重试。\n')
    })

    req.on('aborted', () => upstream.destroy())
    res.on('close', () => upstream.destroy())
    req.pipe(upstream)
  }
}

export const name = 'dsh-game'
export const inject = ['webServer']

export function apply(ctx) {
  const handler = createHandler(ctx)
  ctx.effect(() => {
    const dispose = ctx.webServer.register({
      kind: 'prefix',
      path: ROUTE_PATH,
      handler,
    })
    return () => {
      if (typeof dispose === 'function') dispose()
    }
  }, 'dsh-game: /game reverse proxy')
}
