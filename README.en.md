<div align="center">

# dsh-game · Poker & Mahjong 「德州扑克 + 麻将」

**Two practice tables inside DSH: heads-up Texas Hold'em and Sichuan mahjong, with hand strength, equity and discard advice.**

Games live only in the backend's memory, and every request goes through DSH's own login gate.

[![Version](https://img.shields.io/badge/version-0.1.0-blue)](package.json)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/DSH-DeepSeek%20Harness-5b5ef7)](https://github.com/frankfurtlin/dsh-pocket)

[中文](README.md) · [English](README.en.md)

</div>

![Texas Hold'em trainer inside the panel](verification/shots/poker-table.png)

## What it is

dsh-game connects the Texas Hold'em trainer and the Sichuan mahjong trainer to the DSH sidebar. Each game starts on its own, and a game exists only in the backend's memory — no database, no files, gone after a restart.

The sidebar's More menu gains two rows, **德州扑克** and **麻将**. Both close the menu and open the same main panel, which switches to the matching tab. The panel is two tabs plus a toolbar (back to chat, reload, open in a new window), and the content is a same-origin iframe. The browser only ever talks to DSH's own `/game/...` paths; the plugin's host half proxies them to `127.0.0.1:8817`, so the backend is never exposed publicly and carries no login logic of its own.

## Features

- **Two entries, one panel** — two rows in the More menu open the same panel on the right tab. Switching tabs keeps one iframe and points it at the other game (`/game/poker/` ↔ `/game/mahjong/`); the game itself survives the reload because its state lives in the backend.
- **Texas Hold'em** — heads-up against an AI: two seats, hole cards, fold / check / call / raise / all-in, a raise slider, hand-strength evaluation, Monte Carlo equity, call EV, a per-hand recommendation, hand history and a session record.
- **Sichuan mahjong** — deal, choose the missing suit (定缺), draw and discard, shanten (向听) and useful-draw (进张) counts, recommended discard, and win checking.
- **Memory-only games** — `server/app/services/game_store.py` keeps games in the uvicorn process with a size cap and LRU eviction; a restart clears everything.
- **Auth by DSH** — every request hits `ctx.connection.requestRejection()` first: 401 when anonymous, 403 when the origin is untrusted. `/game` answers 302 to `/game/`.
- **Proxy details** — strips the `/game` prefix, adds `x-forwarded-*` headers, times out upstream calls after 10s (504) and reports an unreachable upstream as 502.
- **Local only, HTTP only** — the backend listens on `127.0.0.1:8817` and never on `0.0.0.0`; there is no WebSocket, and neither game needs one.
- **Verifiable without installing** — three Node scripts cover app, host and client with 44 assertions in total.

## Install

```bash
# 1) Install the plugin (link: dependency), add it to dsh.profile.bundles, then restart DSH Web:
dsh plugin --profile web add /root/workspace/plugins/dsh-game
# then add "dsh-game" to dsh.profile.bundles in the profile's package.json
systemctl restart deepseek-harness.service

# 2) Start the game backend (FastAPI on 127.0.0.1:8817; in production it runs under systemd):
cd /root/workspace/plugins/dsh-game/server
/usr/bin/python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8817
```

The backend uses the system Python (fastapi 0.142.2 / uvicorn 0.54.0 on this machine); there is no venv. In production the `8817` port is kept alive by a systemd unit whose `WorkingDirectory` points at this repo's `server/`. Port `8917` is reserved for self-tests: the verification scripts start their own instance and kill it afterwards.

Health check: `curl -s http://127.0.0.1:8817/healthz` → `{"ok":true,...}`.

## Configuration

| Where | Key | Meaning |
| --- | --- | --- |
| Host environment | `DSH_GAME_UPSTREAM_PORT` | Upstream port the proxy forwards to; default `8817`. |
| `lib/index.js` | `UPSTREAM_TIMEOUT_MS` | Upstream timeout, default `10000`. It is a code constant, not an env var — edit it if a call ever needs longer. |
| Host (systemd) | unit file | Not distributed with this repo; points at `server/` and binds `127.0.0.1:8817`. |
| Verification env | `DSH_GAME_VERIFY_PORT` | Port the app E2E suite starts its own backend on; default `8917`. |
| Verification env | `DSH_GAME_PROXY_TEST_PORT` | Port the host suite's temporary proxy listens on; default `8898`. |

You do not need to configure the backend at all: it has no database, no storage path and no model keys. Its only state is in process memory.

## Usage

1. Open **More** in the DSH sidebar and pick **德州扑克** or **麻将**. The panel opens on the matching tab.
2. Poker: click **开始牌局** to deal. The table shows both seats, your hole cards and the action buttons; the right-hand panel shows hand strength, your equity, the call EV and a recommendation, and the hand history fills in as you play.
3. Mahjong: click **开始牌局**, choose the missing suit, then draw and discard. Fourteen tiles means it is your turn to discard; the recommended tile is marked, and a valid hand is scored when it is complete.
4. The toolbar keeps **返回对话**, **刷新** and **新窗口打开**. Switching tabs points the iframe at the other game; the backend keeps the game state, so nothing is lost.

## Architecture

```
Browser (DSH Web, 3080)
  └─ /game/**  ──►  lib/index.js (host half, Cordis)
                     · ctx.connection.requestRejection(): 401 anonymous / 403 untrusted
                     · /game → 302 /game/
                     · strip the /game prefix, add x-forwarded-*, 10s timeout → 504, unreachable → 502
                     └─►  127.0.0.1:8817  FastAPI (server/app, kept alive by systemd)
                            · GET /poker/、/poker/api/{new,state,action}
                            · GET /mahjong/、/mahjong/api/{new,state,action}
                            · rules / evaluation / AI are pure-logic packages copied from betterlife
```

The client half is hand-written: it registers `window.__ModuleLoader__` itself, adds a main panel with `key='dsh-game'` and two rows on `sidebar.panellist.actions`. It depends only on the host-provided `react` and the optional `@deepseek-ai/dsh-client-ui-primitives`; when the primitives are missing it falls back to plain buttons.

## Verification

All three scripts run without installing the plugin; they start and clean up their own backend, and use the Playwright copy already on this machine when needed:

```bash
cd /root/workspace/plugins/dsh-game
node verification/verify-app.mjs      # Playwright: click through both games (19 checks)
node verification/verify-host.mjs     # proxy + auth gate (8 checks)
node verification/verify-client.mjs   # client registration shape + component rendering (17 checks)
```

Measured on 2026-11-04: **19 PASS / 0 FAIL**, **8 PASS / 0 FAIL**, **17 PASS / 0 FAIL**, with no console errors.

- `verification/shots/poker-table.png` — after clicking 开始牌局: two seats, your hole cards face up, five action buttons.
- `verification/shots/mahjong-table.png` — after 开始牌局 → 定缺 → draw (14 tiles) → clicking the recommended discard: hand and table fully rendered.

What the app suite asserts: `/poker/` deals via `POST /poker/api/new` (200), the table renders with two `.seat` nodes, hole cards get a face, and 跟注 posts `/poker/api/action`; `/mahjong/` deals 13 tiles, 定缺 and discard both post actions successfully, and the hand grows to 14 tiles; neither page keeps a `/mine` absolute-path leftover and neither raises console errors.

The host suite uses a fake `ctx.connection` and port 8898 to prove prefix stripping, 401/403 blocking before the proxy, the `/game` → `/game/` redirect, 404 passthrough and 502 when the upstream is down. The client suite uses mocked `slots`/`layout` to prove the registration shape, tab switching, iframe URL, menu-click order (`onDismiss` → `open` → `selectPanel('dsh-game')`) and the fallback when UI primitives are absent.

These suites cover the plugin's own logic. Whether the two menu rows and the `/game/` proxy render correctly inside a real DSH instance is covered by the mount itself — if that fails, start with the `dsh-game` load errors in the DSH log.

## Repository layout

| Path | Contents |
| --- | --- |
| `lib/index.js` | Host half: `/game` reverse proxy plus the DSH auth gate (prefix handler). |
| `client.js` | Client half: hand-written `window.__ModuleLoader__` factory; main panel at `key='dsh-game'`; two rows on `sidebar.panellist.actions`. |
| `server/app/main.py` | FastAPI composition root: mounts both routers, a small two-entry root page and `/healthz`. |
| `server/app/domains/poker/` | Hold'em engine (cards / game / evaluator / equity / ai) plus `web.html`. Copied verbatim, logic unchanged. |
| `server/app/domains/mahjong/` | Mahjong engine (tiles / hand / game / ai) plus `web.html`. Same. |
| `server/app/api/routes/` | HTTP adapter layer (`/poker`, `/mahjong` prefixes). |
| `server/app/services/game_store.py` | In-memory game store (size cap plus LRU eviction on read). |
| `verification/` | Three verification scripts plus `shots/`. |
| `cordis.patch.yml` | Bundle patch; `id` must equal the package name `dsh-game`. |

## Relationship to betterlife

The game rules, hand evaluation, Monte Carlo simulation, AI, mahjong shanten and useful-draw calculation were copied from betterlife (`app/domains/poker/**`, `app/domains/mahjong/**`, `app/services/game_store.py`) and not rewritten. Only three things changed:

1. Route prefixes: `/mine/poker` → `/poker`, `/mine/mahjong` → `/mahjong`. Error bodies keep FastAPI's default `{"detail": ...}`.
2. API base URLs in `web.html` are relative (the pages live at `/poker/` and `/mahjong/`), and the `/mine` favicon reference became an inline data URI.
3. betterlife's login middleware and unified error handler were dropped; auth is now the DSH proxy gate.

## Known limitations

- **In-memory state**: both games live in the uvicorn process, so a restart clears them, and multiple workers would lose games. Run a single worker.
- **10s proxy timeout**: measured calls finish within 1s; anything longer gets a 504. Change `UPSTREAM_TIMEOUT_MS` in `lib/index.js` if that ever matters.
- **HTTP only**: no WebSocket proxying; neither game uses long connections.
- **Prefix-mounted**: any path added under `/poker` or `/mahjong` becomes reachable through `/game` automatically, and nothing outside those prefixes can be used by the pages.
- **No backend auth**: never expose port 8817 on `0.0.0.0` or on the public internet. The only supported entry point is DSH's `/game`.
- **No `node_modules`**: the client relies on the host-injected `react` and on the optional UI primitives, and degrades gracefully without them.
