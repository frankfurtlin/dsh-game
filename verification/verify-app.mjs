#!/usr/bin/env node
/**
 * dsh-game 的端到端验收（Playwright，直连本地后端）。
 *
 * 覆盖两件事，每个断言都真的跑过 DOM 与网络，而不是只看 HTTP 状态码：
 *   1. 扑克：打开 /poker/ → 点「开始牌局」→ `/poker/api/new` 200 → 牌桌可见、
 *      2 个座位、自己的 2 张底牌有牌面、操作按钮出现；点「跟注」→ action 200。
 *   2. 麻将：打开 /mahjong/ → 点「开始牌局」→ `/mahjong/api/new` 200 → 牌桌可见、
 *      自己 13 张手牌渲染；若弹出定缺 → 选一门 → action 200 后仍 13 张。
 * 另外断言两页都没有 `/mine` 绝对路径残留、全程无 console error / pageerror；
 * 截图写到 verification/shots/。
 *
 * 用法：
 *   node verification/verify-app.mjs            # 端口 8917（自测端口，不碰正式 8817）
 *   DSH_GAME_VERIFY_PORT=8899 node ...          # 换端口
 *   SKIP_SERVER_SPAWN=1 node ...                # 已自行起好服务时跳过自动拉起
 *
 * 8917 没服务时脚本会自己用系统 python 拉起 uvicorn（cwd=server/），跑完杀掉；
 * 已有人占着端口则复用、不杀——两种情况都不会留下常驻进程。
 */
import { spawn } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const PORT = Number(process.env.DSH_GAME_VERIFY_PORT || 8917)
const BASE = `http://127.0.0.1:${PORT}`
const SHOTS = join(ROOT, 'verification', 'shots')
const PYTHON = process.env.DSH_GAME_PYTHON || '/usr/bin/python3.11'

/** 断言记录：最后统一打印 PASS/FAIL 总数，任一 FAIL → exit 1。 */
const results = []
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail: detail || '' })
  const suffix = detail ? ` — ${detail}` : ''
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${suffix}`)
}

function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE_DIR,
    join(homedir(), 'workspace/hermes-site/tools/node_modules/'),
    join(ROOT, 'node_modules/'),
  ].filter(Boolean)
  const errors = []
  for (const dir of candidates) {
    try {
      const requireFrom = createRequire(dir.endsWith('/') ? dir : `${dir}/`)
      return requireFrom('playwright')
    } catch (error) {
      errors.push(`${dir}: ${error.message}`)
    }
  }
  throw new Error(`找不到 playwright，试过：\n  ${errors.join('\n  ')}`)
}

async function probeHealth(timeoutMs = 1500) {
  try {
    const response = await fetch(`${BASE}/healthz`, { signal: AbortSignal.timeout(timeoutMs) })
    if (!response.ok) return false
    const body = await response.json()
    return body && body.ok === true
  } catch {
    return false
  }
}

/** 端口上没服务就自己拉起 uvicorn；返回 { proc, owned }。 */
async function ensureServer() {
  if (await probeHealth()) {
    console.log(`· 复用已在运行的 ${BASE}（不会杀它）`)
    return { proc: null, owned: false }
  }
  if (process.env.SKIP_SERVER_SPAWN === '1') {
    throw new Error(`${BASE} 不可用，且 SKIP_SERVER_SPAWN=1 禁止自动拉起`)
  }
  console.log(`· 拉起后端：${PYTHON} -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`)
  const proc = spawn(
    PYTHON,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(PORT)],
    { cwd: join(ROOT, 'server'), stdio: ['ignore', 'pipe', 'pipe'], env: process.env },
  )
  let output = ''
  proc.stdout.on('data', (chunk) => { output += chunk })
  proc.stderr.on('data', (chunk) => { output += chunk })
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    if (await probeHealth(500)) return { proc, owned: true }
    if (proc.exitCode !== null) {
      throw new Error(`后端起不来（exit=${proc.exitCode}）：\n${output.slice(-2000)}`)
    }
    await new Promise((done) => setTimeout(done, 200))
  }
  proc.kill('SIGTERM')
  throw new Error(`后端 30s 内未就绪：\n${output.slice(-2000)}`)
}

/** 关闭自己拉起的后端（等人占用时不动）。 */
async function stopServer(server) {
  if (!server || !server.owned || !server.proc) return
  const proc = server.proc
  if (proc.exitCode !== null) return
  proc.kill('SIGTERM')
  const deadline = Date.now() + 5000
  while (Date.now() < deadline && proc.exitCode === null) {
    await new Promise((done) => setTimeout(done, 100))
  }
  if (proc.exitCode === null) proc.kill('SIGKILL')
}

/** 等待某个 URL 的响应，同时执行触发动作（避免先点后等的竞态）。 */
async function actionWithResponse(page, trigger, urlPart, method) {
  const [response] = await Promise.all([
    page.waitForResponse(
      (res) => res.url().includes(urlPart) && (!method || res.request().method() === method),
      { timeout: 15_000 },
    ),
    trigger(),
  ])
  return response
}

async function verifyPoker(page) {
  console.log('\n▶ 扑克 /poker/')
  await page.goto(`${BASE}/poker/`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('#lobby .start-btn', { timeout: 10_000 })

  const html = await page.content()
  check('扑克页面无 /mine 绝对路径残留', !html.includes('/mine'))

  const newResponse = await actionWithResponse(page, () => page.click('#lobby .start-btn'), '/poker/api/new', 'POST')
  check('点「开始牌局」→ POST /poker/api/new 200', newResponse.status() === 200, `status=${newResponse.status()}`)

  const state = await newResponse.json()
  check(
    '新牌局返回 game_id 与 2 张底牌',
    Boolean(state && state.game_id) && Array.isArray(state.hero_hole) && state.hero_hole.length === 2,
    `game_id=${state && state.game_id} hero_hole=${JSON.stringify(state && state.hero_hole)}`,
  )

  await page.waitForSelector('#tableWrap', { state: 'visible', timeout: 10_000 })
  const seats = await page.locator('#seats .seat').count()
  check('牌桌渲染 2 个座位', seats === 2, `seats=${seats}`)

  // 自己座位的底牌必须真的有牌面（.cn 是点数），不是只有牌背。
  await page.waitForFunction(
    () => document.querySelectorAll('#seats .seat.p0 .hand .card .cn').length === 2,
    undefined,
    { timeout: 10_000 },
  )
  const heroFaces = await page.locator('#seats .seat.p0 .hand .card .cn').allTextContents()
  check('自己的底牌有牌面', heroFaces.length === 2, `faces=${heroFaces.join(',')}`)

  const actionCount = await page.locator('#actions button').count()
  check('轮到玩家时出现操作按钮', actionCount > 0, `buttons=${actionCount}`)

  // 真实点一次合法操作，验证 action 接口也通（不是只测了开新局）。
  const callButton = page.locator('#actions .b-call').first()
  if (await callButton.count()) {
    const actionResponse = await actionWithResponse(page, () => callButton.click(), '/poker/api/action/', 'POST')
    check('点「跟注」→ POST /poker/api/action 200', actionResponse.status() === 200, `status=${actionResponse.status()}`)
  } else {
    check('点「跟注」→ POST /poker/api/action 200', false, '没有 .b-call 按钮可点')
  }

  await mkdir(SHOTS, { recursive: true })
  const shot = join(SHOTS, 'poker-table.png')
  await page.screenshot({ path: shot })
  check('扑克截图已写入', true, shot)
}

async function verifyMahjong(page) {
  console.log('\n▶ 麻将 /mahjong/')
  await page.goto(`${BASE}/mahjong/`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('#lobby button.b-gold', { timeout: 10_000 })

  const html = await page.content()
  check('麻将页面无 /mine 绝对路径残留', !html.includes('/mine'))

  const newResponse = await actionWithResponse(
    page,
    () => page.click('#lobby button.b-gold'),
    '/mahjong/api/new',
    'POST',
  )
  check('点「开始牌局」→ POST /mahjong/api/new 200', newResponse.status() === 200, `status=${newResponse.status()}`)
  const payload = await newResponse.json()
  check(
    '新牌局返回 game_id 与 13 张手牌',
    Boolean(payload && payload.game_id) &&
      Array.isArray(payload.state && payload.state.players && payload.state.players[0].hand) &&
      payload.state.players[0].hand.length === 13,
    `game_id=${payload && payload.game_id}`,
  )

  await page.waitForSelector('#tableWrap', { state: 'visible', timeout: 10_000 })
  await page.waitForFunction(
    () => document.querySelectorAll('#seatMe .handrow .tile').length === 13,
    undefined,
    { timeout: 10_000 },
  )
  const myTiles = await page.locator('#seatMe .handrow .tile').count()
  check('自己的 13 张手牌已渲染', myTiles === 13, `tiles=${myTiles}`)

  // 开局必弹定缺：选一门；定缺会打掉一张缺门牌并摸一张，所以手牌 13 → 14。
  const voidVisible = await page.locator('#voidModal.show .suitbtn').count()
  if (voidVisible > 0) {
    const voidResponse = await actionWithResponse(
      page,
      () => page.locator('#voidModal.show .suitbtn').first().click(),
      '/mahjong/api/action/',
      'POST',
    )
    check('定缺 → POST /mahjong/api/action 200', voidResponse.status() === 200, `status=${voidResponse.status()}`)
    await page.waitForFunction(
      () => document.querySelectorAll('#seatMe .handrow .tile').length === 14,
      undefined,
      { timeout: 10_000 },
    )
    check('定缺后摸牌：手牌变为 14 张待打', (await page.locator('#seatMe .handrow .tile').count()) === 14)
  } else {
    check('开局定缺弹窗出现', false, '未出现 #voidModal.show .suitbtn')
  }

  // 真实点一张推荐牌（.best 带 onclick），验证 discard 接口并回到 13 张。
  const bestTile = page.locator('#seatMe .handrow .tile.best').first()
  if (await bestTile.count()) {
    const discardResponse = await actionWithResponse(page, () => bestTile.click(), '/mahjong/api/action/', 'POST')
    check('点推荐手牌出牌 → POST /mahjong/api/action 200', discardResponse.status() === 200, `status=${discardResponse.status()}`)
    const discarded = await discardResponse.json()
    const handAfter = discarded && discarded.state && discarded.state.players
      ? discarded.state.players[0].hand.length
      : -1
    check('出牌后手牌保持满手（13/14 张）', handAfter === 13 || handAfter === 14, `hand=${handAfter}`)
    await page.waitForFunction(
      () => {
        const n = document.querySelectorAll('#seatMe .handrow .tile').length
        return n === 13 || n === 14
      },
      undefined,
      { timeout: 10_000 },
    )
    check('出牌后手牌渲染未丢失', (await page.locator('#seatMe .handrow .tile').count()) >= 13)
  } else {
    check('点推荐手牌出牌 → POST /mahjong/api/action 200', false, '没有 .tile.best 可点')
  }

  await mkdir(SHOTS, { recursive: true })
  const shot = join(SHOTS, 'mahjong-table.png')
  await page.screenshot({ path: shot })
  check('麻将截图已写入', true, shot)
}

async function main() {
  await mkdir(SHOTS, { recursive: true })
  const server = await ensureServer()
  let browser = null
  try {
    const { chromium } = loadPlaywright()
    browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] })
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()

    const consoleErrors = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`))

    await verifyPoker(page)
    await verifyMahjong(page)

    check('全程无 console error / pageerror', consoleErrors.length === 0, consoleErrors.join(' | ').slice(0, 600))
  } finally {
    if (browser) await browser.close()
    await stopServer(server)
  }

  const passed = results.filter((r) => r.ok).length
  const failed = results.length - passed
  console.log(`\n${failed === 0 ? '✅' : '❌'} ${passed} PASS / ${failed} FAIL（共 ${results.length} 项）`)
  if (failed > 0) {
    for (const r of results.filter((item) => !item.ok)) console.log(`   FAIL: ${r.name}${r.detail ? ` — ${r.detail}` : ''}`)
    process.exitCode = 1
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error)
  process.exitCode = 1
})
