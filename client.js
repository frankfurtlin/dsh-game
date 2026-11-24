/**
 * dsh-game —— client 半（浏览器）。
 *
 * 手写 ModuleLoader 工厂，不经打包：只依赖宿主已提供的 react，用 h() 直接构造元素。
 * 做两件事：
 *   1. 在侧栏「更多」菜单（sidebar.panellist.actions）注册**一行「游戏」**：点它会
 *      onDismiss 关菜单，再 layout.selectPanel 打开主面板（保留上次的 tab，默认扑克）。
 *      扑克/麻将不再各占一行，改由面板内的 tab 切换 —— 不注册 sideb.panellist 常驻行。
 *   2. 在 main 座位注册 keyed 面板（key = 'dsh-game'）：工具条（返回对话 / 刷新 /
 *      新窗口 + 扑克/麻将两个 tab 按钮）+ 同源 iframe（/game/poker/ 或
 *      /game/mahjong/，反代见 lib/index.js）。
 *
 * tab 状态放在模块作用域：面板没挂载时点菜单 → 记下待选 tab，挂载时直接用它；
 * 面板已挂载时点菜单 → 通过订阅者即时切 tab。两种路径都不会出现「点了却停在旧 tab」。
 */
window.__ModuleLoader__.load({
  id: "dsh-game",
  factory: function (require) {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    var react = require("react");
    var h = react.createElement;

    /** 面板 id —— main 座位的 key，也是「更多」菜单那一行的锚点。 */
    var PANEL_ID = "dsh-game";
    /** 「更多」菜单里的排序：排在插件类入口之后（调酒是 40）。 */
    var MORE_ORDER = 41;

    /** 两个 tab 的元数据；kind 同时是 URL 段（/game/<kind>/）与 data 锚点。 */
    var TABS = [
      {
        kind: "poker",
        label: "德州扑克",
        title: "德州扑克 · 训练器",
        subtitle: "胜率 / 底池赔率 / GTO 建议",
      },
      {
        kind: "mahjong",
        label: "麻将",
        title: "四川麻将 · 训练器",
        subtitle: "向听数 / 有效进张 / 推荐打牌",
      },
    ];

    /** 宿主 UI 基础组件；某些版本可能不向第三方插件导出，缺失时退回原生按钮。 */
    var primitives = null;
    try {
      primitives = require("@deepseek-ai/dsh-client-ui-primitives");
    } catch (error) {
      primitives = null;
    }

    var COLORS = {
      border: "color-mix(in srgb, currentColor 18%, transparent)",
      muted: "color-mix(in srgb, currentColor 58%, transparent)",
      chip: "color-mix(in srgb, currentColor 8%, transparent)",
      active: "color-mix(in srgb, currentColor 16%, transparent)",
    };

    // ---------------------------------------------------------------- tab 状态

    /** 当前选中的 tab（模块级：面板未挂载时也能记住菜单点了哪一行）。 */
    var activeTab = "poker";
    /** 面板挂载期间的订阅者：菜单点击 → 已挂载的面板立即切 tab。 */
    var tabListeners = [];

    function isTabKind(kind) {
      return kind === "poker" || kind === "mahjong";
    }

    function tabInfo(kind) {
      for (var i = 0; i < TABS.length; i += 1) {
        if (TABS[i].kind === kind) return TABS[i];
      }
      return TABS[0];
    }

    function setActiveTab(kind) {
      var next = isTabKind(kind) ? kind : "poker";
      if (next === activeTab) return;
      activeTab = next;
      var listeners = tabListeners.slice();
      for (var i = 0; i < listeners.length; i += 1) {
        try {
          listeners[i](activeTab);
        } catch (error) {
          console.warn("[dsh-game] tab 订阅者抛错:", error);
        }
      }
    }

    function subscribeTab(listener) {
      tabListeners.push(listener);
      return function () {
        var index = tabListeners.indexOf(listener);
        if (index !== -1) tabListeners.splice(index, 1);
      };
    }

    /** 应用页地址：相对 DSH 的 base 拼，宿主挂在子路径下也能用。 */
    function appHref(kind) {
      try {
        return new URL("game/" + kind + "/", document.baseURI).href;
      } catch (error) {
        return "/game/" + kind + "/";
      }
    }

    // ---------------------------------------------------------------- 图标

    /** 扑克筹码：同心圆 + 刻度（currentColor，跟随主题）。 */
    function PokerIcon(props) {
      var size = (props && props.size) || 16;
      return h(
        "svg",
        {
          viewBox: "0 0 16 16",
          width: size,
          height: size,
          fill: "none",
          stroke: "currentColor",
          strokeWidth: 1.3,
          strokeLinecap: "round",
          "aria-hidden": "true",
          focusable: "false",
        },
        h("circle", { cx: 8, cy: 8, r: 5.6 }),
        h("circle", { cx: 8, cy: 8, r: 2.4 }),
        h("path", { d: "M8 2.4v1.6M8 12v1.6M2.4 8h1.6M12 8h1.6" }),
      );
    }

    /** 麻将牌：圆角方块 + 中。
     */
    function MahjongIcon(props) {
      var size = (props && props.size) || 16;
      return h(
        "svg",
        {
          viewBox: "0 0 16 16",
          width: size,
          height: size,
          fill: "none",
          stroke: "currentColor",
          strokeWidth: 1.3,
          strokeLinejoin: "round",
          "aria-hidden": "true",
          focusable: "false",
        },
        h("rect", { x: 2.6, y: 1.8, width: 10.8, height: 12.4, rx: 2 }),
        h("circle", { cx: 8, cy: 8, r: 2.7 }),
        h("path", { d: "M5.6 5.6h4.8v4.8H5.6z", opacity: 0 }),
      );
    }

    /** 游戏手柄：「更多」菜单里「游戏」这一行用，扑克/麻将合并在面板内切 tab。 */
    function GameIcon(props) {
      var size = (props && props.size) || 16;
      return h(
        "svg",
        {
          viewBox: "0 0 16 16",
          width: size,
          height: size,
          fill: "none",
          stroke: "currentColor",
          strokeWidth: 1.3,
          strokeLinecap: "round",
          strokeLinejoin: "round",
          "aria-hidden": "true",
          focusable: "false",
        },
        h("rect", { x: 1.6, y: 4.6, width: 12.8, height: 6.8, rx: 3.4 }),
        h("path", { d: "M5.1 6.9v3.2M3.5 8.5h3.2" }),
        h("circle", { cx: 10.5, cy: 7.7, r: 0.75 }),
        h("circle", { cx: 11.8, cy: 9.3, r: 0.75 }),
      );
    }

    function tabIcon(kind, size) {
      return kind === "mahjong" ? h(MahjongIcon, { size: size }) : h(PokerIcon, { size: size });
    }

    // ---------------------------------------------------------------- 组件

    function ToolbarButton(props) {
      return h(
        "button",
        {
          type: "button",
          onClick: props.onClick,
          title: props.title || "",
          "data-dsh-game-action": props.action || "",
          style: {
            appearance: "none",
            padding: "4px 11px",
            borderRadius: 7,
            border: "1px solid " + COLORS.border,
            background: props.primary ? COLORS.active : "transparent",
            color: "inherit",
            font: "inherit",
            fontSize: 12,
            lineHeight: "20px",
            cursor: "pointer",
            whiteSpace: "nowrap",
          },
        },
        props.children,
      );
    }

    /** 工具条上的 tab 按钮：选中态用底色 + 加粗。 */
    function TabButton(props) {
      var info = props.info;
      var selected = props.selected;
      return h(
        "button",
        {
          type: "button",
          role: "tab",
          "aria-selected": selected ? "true" : "false",
          "data-dsh-game-tab": info.kind,
          onClick: props.onClick,
          title: info.title,
          style: {
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            appearance: "none",
            padding: "4px 12px",
            borderRadius: 7,
            border: "1px solid " + (selected ? "transparent" : COLORS.border),
            background: selected ? COLORS.active : "transparent",
            color: "inherit",
            font: "inherit",
            fontSize: 13,
            fontWeight: selected ? 600 : 400,
            cursor: "pointer",
            whiteSpace: "nowrap",
          },
        },
        tabIcon(info.kind, 15),
        h("span", null, info.label),
      );
    }

    /** 主面板页：工具条（tab + 操作）+ 同源 iframe。 */
    function GamePanelPage(props) {
      var injected = props || {};
      var frameRef = react.useRef(null);
      var [tab, setTab] = react.useState(activeTab);

      // 与模块级 tab 状态双向同步：挂载时取当前值，挂载期间菜单点击直接切。
      react.useEffect(function () {
        setTab(activeTab);
        return subscribeTab(function (kind) {
          setTab(kind);
        });
      }, []);

      var info = tabInfo(tab);
      var src = appHref(tab);

      var reload = function () {
        var frame = frameRef.current;
        // 直接改 DOM src：只重载 iframe，不重挂整个面板组件。
        if (frame) frame.src = src + "?t=" + Date.now();
      };
      var backToConversation = function () {
        try {
          if (injected.selectConversation) injected.selectConversation();
        } catch (error) {
          console.warn("[dsh-game] 返回对话失败:", error);
        }
      };

      return h(
        "div",
        {
          "data-dsh-game-panel": "",
          "data-dsh-game-active-tab": tab,
          style: {
            display: "flex",
            flexDirection: "column",
            height: "100%",
            minHeight: 0,
            width: "100%",
          },
        },
        h(
          "div",
          {
            style: {
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 14px",
              borderBottom: "1px solid " + COLORS.border,
              flexShrink: 0,
              flexWrap: "wrap",
            },
          },
          h("span", { style: { fontSize: 14, fontWeight: 600 } }, "游戏"),
          h(
            "span",
            { style: { display: "inline-flex", gap: 4 } },
            TABS.map(function (item) {
              return h(TabButton, {
                key: item.kind,
                info: item,
                selected: item.kind === tab,
                onClick: function () {
                  setActiveTab(item.kind);
                },
              });
            }),
          ),
          h("span", {
            "data-dsh-game-subtitle": "",
            style: { fontSize: 12, color: COLORS.muted },
          }, info.subtitle),
          h("span", { style: { flex: 1 } }),
          h(
            ToolbarButton,
            {
              action: "back",
              onClick: backToConversation,
              title: "回到对话",
            },
            "返回对话",
          ),
          h(
            ToolbarButton,
            { action: "reload", onClick: reload, title: "重新加载当前游戏页面" },
            "刷新",
          ),
          h(
            "a",
            {
              "data-dsh-game-action": "open",
              href: src,
              target: "_blank",
              rel: "noreferrer",
              style: { fontSize: 12, color: COLORS.muted, textDecoration: "none" },
            },
            "新窗口打开",
          ),
        ),
        h("iframe", {
          ref: frameRef,
          src: src,
          title: info.title,
          "data-dsh-game-frame": "",
          style: {
            flex: 1,
            minHeight: 0,
            width: "100%",
            border: 0,
            background: "transparent",
          },
        }),
      );
    }

    /**
     * 「更多」菜单里的唯一一行「游戏」：先关菜单，再打开面板。
     * 扑克 / 麻将由面板内工具条切 tab，菜单不再按玩法分行。
     */
    function GameMenuItem(props) {
      var injected = props || {};
      var onSelect = function () {
        if (typeof props.onDismiss === "function") {
          try {
            props.onDismiss();
          } catch (error) {
            console.warn("[dsh-game] 关闭「更多」菜单失败:", error);
          }
        }
        if (typeof injected.open === "function") injected.open();
      };
      if (primitives && primitives.MenuItemButton) {
        return h(
          primitives.MenuItemButton,
          { onSelect: onSelect, icon: h(GameIcon, { size: 16 }) },
          h("span", { "data-dsh-game-more": "game" }, "游戏"),
        );
      }
      return h(
        "button",
        {
          type: "button",
          role: "menuitem",
          onClick: onSelect,
          "data-dsh-game-more": "game",
          style: {
            display: "flex",
            alignItems: "center",
            gap: 8,
            width: "100%",
            padding: "7px 12px",
            border: 0,
            borderRadius: 6,
            background: "transparent",
            color: "inherit",
            font: "inherit",
            fontSize: 13,
            textAlign: "left",
            cursor: "pointer",
          },
        },
        h(GameIcon, { size: 16 }),
        h("span", null, "游戏"),
      );
    }

    // ---------------------------------------------------------------- 注册

    /** 由宿主注入的服务签名：客户端根 context。 */
    var inject = ["slots", "layout"];

    function apply(ctx) {
      var disposers = [];

      /** 打开游戏面板；kind 可选（面板工具条也用这条路径切 tab），不传就保留当前 tab。 */
      var openGame = function (kind) {
        if (kind) setActiveTab(kind);
        try {
          ctx.layout.selectPanel(PANEL_ID);
        } catch (error) {
          console.warn("[dsh-game] 打开面板失败:", error);
        }
      };
      var selectConversation = function () {
        try {
          ctx.layout.selectPanel(null);
        } catch (error) {
          console.warn("[dsh-game] 返回对话失败:", error);
        }
      };

      try {
        var slots = ctx.slots;
        // main 座位必须先注册：菜单点击时 selectPanel 才有目标。
        disposers.push(
          slots.inject("main", function () {
            return slots.register(
              {
                name: "main",
                key: PANEL_ID,
                inject: function () {
                  return { selectConversation: selectConversation };
                },
              },
              GamePanelPage,
            );
          }),
        );
        // 「更多」菜单一行「游戏」：扑克/麻将合并成一个入口，面板内再切 tab。
        disposers.push(
          slots.inject("sidebar.panellist.actions", function () {
            return slots.register(
              {
                name: "sidebar.panellist.actions",
                id: "dsh-game-more",
                order: MORE_ORDER,
                inject: function () {
                  return { open: openGame };
                },
              },
              GameMenuItem,
            );
          }),
        );
      } catch (error) {
        console.warn("[dsh-game] panel registration failed:", error);
      }

      ctx.effect(function () {
        return function () {
          for (var i = 0; i < disposers.length; i += 1) {
            try {
              disposers[i]();
            } catch {}
          }
          disposers.length = 0;
        };
      }, "dsh-game: ui mounts");
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
