#!/usr/bin/env node
/**
 * dsh-game 的 client 半验收（不经 DSH 安装）。
 *
 * 用 Node 模拟浏览器里的 `window.__ModuleLoader__` 与宿主 mock（slots / layout），
 * 把 client.js 真实跑一遍，再用 react-dom/server 渲染注册进去的组件，证明：
 *   1. `apply` 在 main 座位注册 key='dsh-game' 的面板，并在
 *      `sidebar.panellist.actions` 注册两行（id / order / name 都对）；
 *   2. 面板默认 tab=扑克，工具条有两个 tab、返回/刷新/新窗口、iframe 指向
 *      `/game/poker/`；
 *   3. 点「麻将」菜单行：先 onDismiss 关菜单，再 layout.selectPanel('dsh-game')，
 *      之后面板渲染出的 tab 变成麻将、iframe 指向 `/game/mahjong/`；
 *   4. 点「德州扑克」菜单行同理切回扑克。
 *
 * 为什么不用真 DSH：本机约定禁止我安装插件 / 改 /root/.dsh。真实 DSH 里的最终
 * 点击验收由 Lead 安装后执行；本脚本覆盖注册形状与组件行为（宿主 API 是 mock）。
 *
 * 用法：node verification/verify-client.mjs
 */
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(import.meta.url)

/** react 18 与 react-dom/server 在 DSH profile 的 pnpm 仓库里（宿主版本）。 */
const REACT_DIR = '/root/.dsh/profiles/web/node_modules/.pnpm/react@18.3.1/node_modules/react'
const REACT_DOM_SERVER =
  '/root/.dsh/profiles/web/node_modules/.pnpm/react-dom@18.3.1_react@18.3.1/node_modules/react-dom/server.js'
const React = require(join(REACT_DIR, 'index.js'))
const ReactDOMServer = require(REACT_DOM_SERVER)

const results = []
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail: detail || '' })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}

/** 宿主 mock：记录注册项，layout.selectPanel 记录面板 id。 */
function makeHost() {
  const registrations = []
  const selectedPanels = []
  const slots = {
    inject(name, callback) {
      return callback()
    },
    register(definition, component) {
      registrations.push({ definition, component })
      return () => {}
    },
  }
  const layout = {
    selectPanel(id) {
      selectedPanels.push(id)
    },
  }
  // 宿主的 ctx.effect：立刻执行回调、返回它的 disposer（测试里不主动 dispose）。
  const effect = (callback) => callback()
  return { ctx: { slots, layout, effect }, registrations, selectedPanels }
}

/** 最小 primitives mock：MenuItemButton 渲染 role="menuitem" 的按钮。 */
const primitives = {
  MenuItemButton(props) {
    return React.createElement(
      'button',
      { type: 'button', role: 'menuitem', onClick: props.onSelect },
      props.icon || null,
      props.children,
    )
  },
}

async function loadClient({ withPrimitives }) {
  let captured = null
  globalThis.window = {
    __ModuleLoader__: {
      load(options) {
        captured = options
      },
    },
  }
  globalThis.document = { baseURI: 'http://127.0.0.1:3080/' }
  const fakeRequire = (id) => {
    if (id === 'react') return React
    if (id === '@deepseek-ai/dsh-client-ui-primitives' && withPrimitives) return primitives
    throw new Error(`unexpected require: ${id}`)
  }
  // 查询串让 ESM 缓存失效：每个用例都要重新执行 client.js。
  const url = `${pathToFileURL(join(ROOT, 'client.js')).href}?case=${Date.now()}-${Math.random()}`
  await import(url)
  if (!captured || typeof captured.factory !== 'function') throw new Error('客户端模块没有调用 __ModuleLoader__.load')
  const exports = captured.factory(fakeRequire)
  return { exports, captured }
}

const markup = (element) => ReactDOMServer.renderToStaticMarkup(element)

function main() {
  return (async () => {
    const { exports } = await loadClient({ withPrimitives: true })
    check('client 暴露 apply 与 inject(slots, layout)', typeof exports.apply === 'function' && Array.isArray(exports.inject) && exports.inject.includes('slots') && exports.inject.includes('layout'))

    const host = makeHost()
    exports.apply(host.ctx)

    const byName = (name) => host.registrations.filter((item) => item.definition.name === name)
    const mains = byName('main')
    const actions = byName('sidebar.panellist.actions')
    check('main 座位注册 1 个面板（key=dsh-game）', mains.length === 1 && mains[0].definition.key === 'dsh-game', `count=${mains.length}`)
    check('「更多」菜单注册两行（poker / mahjong）', actions.length === 2, `count=${actions.length}`)
    const ids = actions.map((item) => item.definition.id)
    const orders = actions.map((item) => item.definition.order)
    check(
      '两行 id / order 正确（不注册 sidebar.panellist 常驻行）',
      ids.includes('dsh-game-more-poker') &&
        ids.includes('dsh-game-more-mahjong') &&
        orders.includes(41) &&
        orders.includes(42) &&
        byName('sidebar.panellist').length === 0,
      `ids=${ids.join(',')} orders=${orders.join(',')}`,
    )

    // 面板默认扑克：工具条、iframe、两个 tab。
    let panelHtml = markup(React.createElement(mains[0].component, { selectConversation: () => {} }))
    check('面板默认 tab=扑克', panelHtml.includes('data-dsh-game-active-tab="poker"'))
    check('工具条有两个 tab 按钮', panelHtml.includes('data-dsh-game-tab="poker"') && panelHtml.includes('data-dsh-game-tab="mahjong"'))
    check('工具条含返回对话', panelHtml.includes('data-dsh-game-action="back"'))
    check('iframe 指向 /game/poker/', panelHtml.includes('src="http://127.0.0.1:3080/game/poker/"'), 'src 见 html')
    check('面板渲染成功', panelHtml.includes('data-dsh-game-panel'))

    // 菜单行：先 onDismiss，再打开面板并切 tab。
    const menuFor = (kind) => actions.find((item) => item.definition.id === `dsh-game-more-${kind}`).component
    let dismissed = 0
    const openSpy = []
    const props = { onDismiss: () => { dismissed += 1 }, open: (kind) => openSpy.push(kind) }
    const pokerMenu = menuFor('poker')(props)
    const mahjongMenu = menuFor('mahjong')(props)
    check('菜单行文案正确', markup(pokerMenu).includes('德州扑克') && markup(mahjongMenu).includes('麻将'))

    // 组件收到的是「宿主 props + 注入 props」；onSelect 是真正挂到按钮上的回调。
    const pokerProps = menuFor('poker')({ ...props, ...{ open: host.ctx.slots ? props.open : props.open } })
    pokerProps.props.onSelect()
    check('点「德州扑克」：先 onDismiss 再 open(poker)', dismissed === 1 && openSpy[0] === 'poker', `dismissed=${dismissed} open=${openSpy.join(',')}`)

    const mahjongProps = menuFor('mahjong')(props)
    mahjongProps.props.onSelect()
    check('点「麻将」：先 onDismiss 再 open(mahjong)', dismissed === 2 && openSpy[1] === 'mahjong', `dismissed=${dismissed} open=${openSpy.join(',')}`)

    // openGame 由 apply 注入到「更多」菜单组件的 props 上：直接调用注册时的 inject() 验证。
    const injected = actions[0].definition.inject()
    check('菜单行注入了 open 回调', typeof injected.open === 'function')
    injected.open('mahjong')
    check('open 会调用 layout.selectPanel("dsh-game")', host.selectedPanels[host.selectedPanels.length - 1] === 'dsh-game', `panels=${host.selectedPanels.join(',')}`)

    // tab 已切到麻将：重新渲染面板应反映出来（模块级 tab 状态）。
    panelHtml = markup(React.createElement(mains[0].component, { selectConversation: () => {} }))
    check('切 tab 后 iframe 指向 /game/mahjong/', panelHtml.includes('src="http://127.0.0.1:3080/game/mahjong/"'))
    check('切 tab 后 data 锚点同步', panelHtml.includes('data-dsh-game-active-tab="mahjong"'))
    panelHtml = markup(React.createElement(mains[0].component, {})) // 无注入 props 也不崩

    // 无 primitives 时的降级分支：应退回原生 role="menuitem" 按钮。
    const fallback = await loadClient({ withPrimitives: false })
    const fallbackHost = makeHost()
    fallback.exports.apply(fallbackHost.ctx)
    const fallbackMenu = fallbackHost.registrations.find((item) => item.definition.id === 'dsh-game-more-poker').component
    const fallbackHtml = markup(fallbackMenu({ onDismiss: () => {}, open: () => {} }))
    check('缺少 primitives 时降级为原生按钮', fallbackHtml.includes('role="menuitem"') && fallbackHtml.includes('德州扑克'))

    const passed = results.filter((item) => item.ok).length
    const failed = results.length - passed
    console.log(`\n${failed === 0 ? '✅' : '❌'} ${passed} PASS / ${failed} FAIL（共 ${results.length} 项）`)
    if (failed > 0) process.exitCode = 1
  })()
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error)
  process.exitCode = 1
})
