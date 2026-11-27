# 德扑训练器 (Texas Hold'em Poker Trainer)

> **本目录是 dsh-game 插件的德扑引擎**（从 betterlife 原样复制，未改规则逻辑）。
> HTTP 层在插件的 `server/app/api/routes/poker.py`，前缀 `/poker`；
> 浏览器经 DSH 反代访问 `/game/poker/`，鉴权由 DSH 的登录闸门负责。
> 本目录只含**纯逻辑**（`cards`/`game`/`evaluator`/`equity`/`ai` + `web.html` + CLI）。

纯 Python 标准库实现的无限制德州扑克训练器，支持 **2–6 人**（你 + 其余 AI）。
目标是**练你的决策**——每次轮到你时实时显示真实胜率、底池赔率、跟注 EV、当前成牌牌型
与 GTO 近似建议，让你对照「直觉」和「数学最优」。

## 快速开始

在 DSH 侧栏「更多」菜单点「游戏」→ 面板里的「德州扑克」tab，或在浏览器打开：

```
http://127.0.0.1:3080/game/poker/
```

**需要 DSH 登录**：`/game` 反代前有鉴权闸门（未登录 401、来源不可信 403），
后端 8817 只监听 `127.0.0.1`，不要直接暴露。

进入页面后：
1. 选择 **单挑·2人** 或 **六人桌·6人**（你 + 5 个 AI，含边池侧池）
2. 选择 AI 风格：松凶 / 紧弱 / GTO近似
3. 点「开始牌局」，轮到你时点 弃牌 / 过牌 / 跟注 / 加注 / **全下**（一键把筹码推完）
4. 右侧「规则」按钮随时查看完整规则

## 命令行版本

```bash
# 在插件根目录（/opt/dsh/dsh-game/server）执行
/usr/bin/python3.11 -m app.domains.poker.cli            # 单挑交互, 默认对手=松凶
/usr/bin/python3.11 -m app.domains.poker.cli n6         # 六人桌交互
/usr/bin/python3.11 -m app.domains.poker.cli demo 200   # 单挑自动对战 200 手
/usr/bin/python3.11 -m app.domains.poker.cli demo 200 n6  # 六人桌自动对战
```

## 决策辅助怎么用

轮到你时界面给四组数字：
- **你的成牌牌型**：翻牌后按「7 张选 5 张」算出你当前最好的牌型（高牌/一对/两对/…）。
- **你的胜率 (equity)**：手牌 + 公共牌，对当前活着的对手做蒙特卡洛模拟的胜率份额
  (win + tie/平局人数)。**多人底池里对手数会被自动计入**，人越多胜率越低。
- **底池赔率要求胜率**：跟注额 / (池子 + 跟注)。equity 高于它才划算。
- **跟注 EV / GTO 近似建议**：简化决策参考（你可以不采纳）。

**一句话玩法**：胜率进度条超过白线（需要的最低胜率）就跟/加，没到就弃。

## 多人 / 边池

- 2 人：按钮位即小盲，翻牌前先动（与原单挑一致）。
- 3–6 人：标准位序（小盲→大盲→UTG→…→按钮），按钮最后动。
- 不足额跟注 / 多人全下时按累计投入**逐层构建边池**，未跟注的超额自动退还，
  摊牌时每个边池由「投入达到该层且未弃牌」的玩家竞争。筹码守恒已用 1500 手随机自测验证。

## 结算明细（`Hand.result`）

前端要说清「谁赢了 / 哪几家平局 / 各拿多少」，靠的是摊牌时逐池记录下来的字段
（v0.66.5 起；`winners`/`pot`/`showdown` 三个旧字段保持不变）：

| 字段 | 含义 |
|------|------|
| `winners` | 拿到过筹码的座位（升序）。**多人 ≠ 平局** —— 边池会让不同人各赢一层 |
| `payouts` | 每个座位从池子里拿回多少；`sum(payouts) == pot`（含奇数筹码那 1 枚） |
| `pots` | 逐池明细 `{amount, eligible, winners:[{seat,amount}], split}`；`split=True` 才是**真正的平局**（同一个池被同牌型的多人平分） |
| `ranks` | 摊牌牌型 `{座位: "两对"}`（弃牌收池时是 `None`），用来解释「为什么他赢 / 为什么平」 |
| `tie` | 是否出现过被平分的池（`winners` 有两人时用它区分「平局」与「各赢一层边池」） |

`web.html` 据此弹一张会自动消失的结算弹窗：赢 😄、输 😭（点名谁赢 + 什么牌型 + 亮底牌）、
平局 🤝（点名哪几家平、各拿多少）；banner 与右侧日志同步说人话。

## 项目结构

| 文件 | 职责 |
|------|------|
| `cards.py` | 扑克牌 / 牌堆 / 洗牌 / 发牌 |
| `evaluator.py` | 7 选 5 手牌评估器（9 档牌型, O(1) 位运算 + 暴力参考对拍） |
| `equity.py` | 蒙特卡洛 equity（支持 1–N 个随机对手, 可选对手范围, 多进程） |
| `game.py` | **多人(2–6)无限注下注状态机**：盲注/轮次/全下/边池/摊牌，筹码守恒不变量；`result` 带逐池结算明细（`payouts`/`pots`/`ranks`/`tie`） |
| `ai.py` | 三种风格 AI：紧弱 / 松凶 / GTO近似，均基于 equity 与底池赔率 |
| `../../api/routes/poker.py`（不在本目录） | FastAPI 路由（前缀 `/poker`），玩家行动后自动推进所有 AI |
| `web.html` | 纯前端：大厅选人数/风格 + N 座位牌桌 + 决策辅助面板 + 自动消失的结算弹窗 |
| `cli.py` | 交互 / 自动对战训练器 |
| `test_evaluator.py` | 评估器：已知牌型 + 排序 + 3000 随机对拍 + 5000 组合一致 |
| `test_game_ai.py` | 状态机 + AI（n=2）：筹码守恒 + 风格强弱 |
| `test_multiway.py` | 多人(2–6) AI 自搏：筹码守恒 + 边池分层 |
| `test_result.py` | 结算明细（固定牌堆）：平局点名 / 边池分层 / 奇数底池 / 弃牌收池 / payouts 分完底池 |

## 运行后端

HTTP 层在插件的 `server/app/api/routes/poker.py`，前缀 `/poker`，由插件的
systemd 单元（端口 8817）常驻；DSH 的 `/game` 反代负责鉴权与外网入口。

对局状态存在**进程内存**里（`GAMES` 字典），重启即清空 —— 训练器没有「续上上一局」的需求，
落库只会引进表结构、清理策略、并发一致性一堆问题。

## 跑测试

```bash
# 在插件根目录的 server/ 下执行
/usr/bin/python3.11 -m pytest app/domains/poker/                     # 全部
/usr/bin/python3.11 -m pytest app/domains/poker/test_evaluator.py    # 评估器：已知牌型+排序+随机对拍
/usr/bin/python3.11 -m pytest app/domains/poker/test_game_ai.py      # AI 互搏(n=2)+风格强弱
/usr/bin/python3.11 -m pytest app/domains/poker/test_multiway.py     # 多人自搏(2–6 人筹码守恒)
/usr/bin/python3.11 -m pytest app/domains/poker/test_result.py       # 结算明细：平局点名/边池分层/奇数底池/弃牌收池
```

## 重要声明

- equity / EV 是**理想化口径**：假设你对所有河牌等可能、对手随机。真实扑克对手有范围、
  读牌、诈唬。界面给的是「基准真相」，不是完整 GTO 解算。
- AI 的「GTO近似」是简化版（跟注阈值=底池赔率，加注随 equity 单调，再叠加少量混合），
  并非真正的纳什均衡求解（那需要 CFR 训练，远超本训练器范围）。
- 三个风格都是**混合策略**：强牌会按概率慢打、弱牌会按概率诈唬。所以「跟注」不等于有牌、
  「加注」也不等于大牌 —— 别指望靠动作把 AI 读死（这是 v0.65.4 专门修掉的破绽）。
- 仅供练习与学习，不涉及真实金钱。

## 已知边界

- 单挑(2人)与多人(3–6人)均已实现，含边池。
- 不实现 read history / 对手建模（更高级的练习方向，可后续扩展）。
- 蒙特卡洛 iters 可调：本目录 `cli.py` 的 `ITERS`；web 端在 `../../api/routes/poker.py`，
  `EQUITY_ITERS`(玩家,高精度)、`AI_ITERS`(AI,低精度,风格由权重驱动)。
