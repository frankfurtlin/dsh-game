#!/usr/bin/env node
/**
 * dsh-game 的 host 半验收（反代逻辑，不经 DSH 安装）。
 *
 * 为什么需要它：接受度测试要在真实 DSH 里装插件才能点「更多」菜单，而本机约定
 * 禁止我改 /root/.dsh 或安装插件。这里把 `lib/index.js` 的 `createHandler` 拉出来，
 * 配一个假的 `ctx.connection`（模拟 DSH 的鉴权闸门）和一个临时 HTTP 端口，
 * 用真实请求证明：
 *
 *   1. 放行时 `/game/...` 被正确剥前缀转给上游（/healthz、/poker/、/poker/api/new）；
 *   2. 未登录 401、主机/来源不可信 403 —— 闸门确实先于反代；
 *   3. `/game` 无尾斜杠 302 → `/game/`；
 *   4. 上游没起来时 502（不是把错误吞掉）。
 *
 * 用法：node verification/verify-host.mjs（内部拉起 8917 后端，跑完杀掉；
 * 临时反代监听 8898，避免与本机其它常驻服务撞端口）。
 * 真实 DSH 内的「更多」菜单两行 / 面板双 tab 由 Lead 安装后人工或 Playwright 验收。
 */
import { spawn } from 'node:child_process'
import { createServer, request as httpRequest } from 'node:http'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const PROXY_PORT = Number(process.env.DSH_GAME_PROXY_TEST_PORT || 8898)
const UPSTREAM_PORT = Number(process.env.DSH_GAME_UPSTREAM_PORT || 8917)
const PYTHON = process.env.DSH_GAME_PYTHON || '/usr/bin/python3.11'
process.env.DSH_GAME_UPSTREAM_PORT = String(UPSTREAM_PORT)

const results = []
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail: detail || '' })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}

/** 极简 HTTP 客户端：返回 { status, headers, body }。 */
function call(path, options = {}) {
  const { method = 'GET', body = null } = options
  return new Promise((resolvePromise, reject) => {
    const req = httpRequest(
      {
        host: '127.0.0.1',
        port: PROXY_PORT,
        path,
        method,
        headers: body ? { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) } : {},
      },
      (res) => {
        const chunks = []
        res.on('data', (chunk) => chunks.push(chunk))
        res.on('end', () =>
          resolvePromise({
            status: res.statusCode,
            headers: res.headers,
            body: Buffer.concat(chunks).toString('utf8'),
          }),
        )
      },
    )
    req.on('error', reject)
    if (body) req.write(body)
    req.end()
  })
}

async function probeHealth() {
  try {
    const response = await fetch(`http://127.0.0.1:${UPSTREAM_PORT}/healthz`, {
      signal: AbortSignal.timeout(1000),
    })
    return response.ok
  } catch {
    return false
  }
}

async function startUpstream() {
  if (await probeHealth()) {
    console.log(`· 复用已在运行的 127.0.0.1:${UPSTREAM_PORT}（不会杀它）`)
    return { proc: null, owned: false }
  }
  const proc = spawn(
    PYTHON,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(UPSTREAM_PORT)],
    { cwd: join(ROOT, 'server'), stdio: ['ignore', 'pipe', 'pipe'], env: process.env },
  )
  let output = ''
  proc.stdout.on('data', (chunk) => { output += chunk })
  proc.stderr.on('data', (chunk) => { output += chunk })
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    if (await probeHealth()) return { proc, owned: true }
    if (proc.exitCode !== null) throw new Error(`后端起不来：\n${output.slice(-1500)}`)
    await new Promise((done) => setTimeout(done, 200))
  }
  proc.kill('SIGTERM')
  throw new Error(`后端 30s 未就绪：\n${output.slice(-1500)}`)
}

async function stopUpstream(upstream) {
  if (!upstream || !upstream.owned || !upstream.proc || upstream.proc.exitCode !== null) return
  upstream.proc.kill('SIGTERM')
  const deadline = Date.now() + 5000
  while (Date.now() < deadline && upstream.proc.exitCode === null) {
    await new Promise((done) => setTimeout(done, 100))
  }
  if (upstream.proc.exitCode === null) upstream.proc.kill('SIGKILL')
}

const { createHandler } = await import('../lib/index.js')

/** 假 ctx：只提供反代与闸门用到的 `get('connection')` / `webServer.register`。 */
function makeFakeCtx(rejection) {
  return {
    get(name) {
      if (name === 'connection') {
        return { requestRejection: () => rejection.value }
      }
      return undefined
    },
  }
}

async function main() {
  /** 由测试逐个改写的闸门返回值：undefined=放行、401、403。 */
  const rejection = { value: undefined }
  const handler = createHandler(makeFakeCtx(rejection))
  const server = createServer((req, res) => handler(req, res))
  // 先占端口再拉后端：端口冲突时不必启动 python，也就不会留下孤儿进程。
  await new Promise((done, fail) => {
    server.once('error', fail)
    server.listen(PROXY_PORT, '127.0.0.1', done)
  })
  console.log(`· 假 DSH 反代监听 http://127.0.0.1:${PROXY_PORT}/game`)

  let upstream = null
  try {
    upstream = await startUpstream()
    let response = await call('/game/healthz')
    check('放行：GET /game/healthz → 200 且剥掉 /game 前缀', response.status === 200 && response.body.includes('"ok":true'), `status=${response.status} body=${response.body.slice(0, 60)}`)

    response = await call('/game?x=1')
    check(
      'GET /game?x=1 → 302 /game/?x=1',
      response.status === 302 && response.headers.location === '/game/?x=1',
      `status=${response.status} location=${response.headers.location}`,
    )

    response = await call('/game/poker/')
    check(
      'GET /game/poker/ → 200 页面',
      response.status === 200 && (response.headers['content-type'] || '').includes('text/html') && response.body.includes('开始牌局'),
      `status=${response.status} type=${response.headers['content-type']}`,
    )

    response = await call('/game/poker/api/new', {
      method: 'POST',
      body: JSON.stringify({ n_players: 2, ai_style: 'loose_aggressive', stacks: 200 }),
    })
    let gameId = ''
    try { gameId = JSON.parse(response.body).game_id } catch {}
    check('放行：POST /game/poker/api/new → 200 且带 game_id', response.status === 200 && Boolean(gameId), `status=${response.status} game_id=${gameId}`)

    response = await call('/game/no-such-path')
    check('未知路径：GET /game/no-such-path → 404（透传后端 404）', response.status === 404, `status=${response.status}`)

    rejection.value = 401
    response = await call('/game/poker/')
    check('未登录：GET /game/poker/ → 401（闸门先于反代）', response.status === 401, `status=${response.status}`)

    rejection.value = 403
    response = await call('/game/mahjong/')
    check('来源不可信：GET /game/mahjong/ → 403', response.status === 403, `status=${response.status}`)

    rejection.value = undefined
    await stopUpstream(upstream)
    response = await call('/game/healthz')
    check('上游未启动：GET /game/healthz → 502', response.status === 502, `status=${response.status}`)
  } finally {
    await new Promise((done) => server.close(done))
    await stopUpstream(upstream)
  }

  const passed = results.filter((item) => item.ok).length
  const failed = results.length - passed
  console.log(`\n${failed === 0 ? '✅' : '❌'} ${passed} PASS / ${failed} FAIL（共 ${results.length} 项）`)
  if (failed > 0) process.exitCode = 1
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error)
  process.exitCode = 1
})
