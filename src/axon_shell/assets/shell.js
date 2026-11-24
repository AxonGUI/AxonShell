/* axon-shell 皮肤：标题栏 / 菜单 / 窗口按钮 / 右键菜单 / 窗口状态
 *
 * 用法（普通 <script>，不需要打包）：
 *
 *   <link rel="stylesheet" href="/axon-shell/shell.css">
 *   <script src="/vendor/axon.umd.cjs"></script>
 *   <script src="/axon-shell/shell.js"></script>
 *   <script>
 *     const shell = AxonShell.mount({
 *       title: "My App",
 *       menus: [{ id: "file", label: "文件", items: [
 *         { id: "new", label: "新建", shortcut: "Ctrl+N", run() {} },
 *       ]}],
 *     });
 *   </script>
 *
 * 它只负责「外壳」：窗口按钮、拖拽区、菜单渲染、缩放（非 Windows）。
 * 业务逻辑（菜单点下去做什么）留在你自己的代码里。
 */
(function (global) {
  "use strict";

  const ICONS = {
    min: '<svg viewBox="0 0 16 16"><path d="M3 8.5h10"/></svg>',
    max: '<svg viewBox="0 0 16 16"><rect x="3.2" y="3.2" width="9.6" height="9.6" rx="1.2"/></svg>',
    restore:
      '<svg viewBox="0 0 16 16"><rect x="3.2" y="5.2" width="7.6" height="7.6" rx="1"/><path d="M5.6 5.2V4.2a1 1 0 0 1 1-1h5.2a1 1 0 0 1 1 1v5.2a1 1 0 0 1-1 1h-1"/></svg>',
    close: '<svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
  };

  const state = {
    platform: "linux",
    frame: { x: 0, y: 0, width: 0, height: 0 },
    maximized: false,
    fullScreen: false,
    menuEl: null,
    menuAnchor: null,
    nativeHost: null,
    listeners: { command: [], state: [], nativeMenu: [] },
  };

  const $ = (id) => document.getElementById(id);

  function axon() {
    const lib = global.axon;
    if (!lib) throw new Error("axon-shell: 先加载 axon 的 UMD 产物（window.axon）");
    return lib;
  }

  function logError(err) {
    // 不打断外壳：打印出来，业务自己决定怎么提示
    console.error("[axon-shell]", err);
  }

  function emit(kind, payload) {
    for (const cb of state.listeners[kind]) {
      try {
        cb(payload);
      } catch (err) {
        logError(err);
      }
    }
  }

  /* ── 主题 ─────────────────────────────────────────────── */
  function setTheme(theme) {
    const value = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.axsTheme = value;
    try {
      localStorage.setItem("axs-theme", value);
    } catch {
      /* 无痕模式下写不进去，忽略 */
    }
    return value;
  }

  function toggleTheme() {
    return setTheme(document.documentElement.dataset.axsTheme === "light" ? "dark" : "light");
  }

  function initTheme() {
    let saved = null;
    try {
      saved = localStorage.getItem("axs-theme");
    } catch {
      saved = null;
    }
    if (saved !== "light" && saved !== "dark") {
      saved = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    setTheme(saved);
  }

  /* ── 弹出菜单 ─────────────────────────────────────────── */
  function closeMenu() {
    state.menuEl?.remove();
    state.menuEl = null;
    state.menuAnchor?.classList.remove("is-open");
    state.menuAnchor = null;
  }

  function menu(items, x, y, opts = {}) {
    closeMenu();
    const el = document.createElement("div");
    el.className = "axs-menu" + (opts.className ? " " + opts.className : "");
    el.setAttribute("role", "menu");

    for (const item of items || []) {
      if (item.kind === "separator") {
        const sep = document.createElement("div");
        sep.className = "axs-menu__sep";
        el.appendChild(sep);
        continue;
      }
      const btn = document.createElement("button");
      btn.className = "axs-menu__item";
      btn.type = "button";
      if (item.id) btn.dataset.id = item.id;
      if (item.kind === "check" || item.kind === "radio") btn.dataset.kind = item.kind;
      if (item.disabled) btn.disabled = true;

      const checked = typeof item.checked === "function" ? item.checked() : item.checked === true;
      if (item.kind === "check" || item.kind === "radio") btn.dataset.checked = String(!!checked);

      const label = document.createElement("span");
      label.textContent = item.label || "";
      btn.appendChild(label);

      if (item.items?.length) {
        const arrow = document.createElement("span");
        arrow.className = "arrow";
        arrow.textContent = "›";
        btn.appendChild(arrow);
        btn.addEventListener("mouseenter", () => {
          const rect = btn.getBoundingClientRect();
          menu(item.items, rect.right - 4, rect.top - 4, { submenu: true });
        });
      } else if (item.shortcut) {
        const sc = document.createElement("span");
        sc.className = "sc";
        sc.textContent = item.shortcut;
        btn.appendChild(sc);
      }

      btn.addEventListener("click", async () => {
        closeMenu();
        if (item.disabled) return;
        try {
          if (item.run) await item.run(item);
          else emit("command", item);
        } catch (err) {
          logError(err);
        }
      });

      el.appendChild(btn);
    }

    document.body.appendChild(el);
    const rect = el.getBoundingClientRect();
    const left = Math.max(6, Math.min(x, innerWidth - rect.width - 8));
    const top = Math.max(6, Math.min(y, innerHeight - rect.height - 8));
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    state.menuEl = el;
    state.menuAnchor = opts.anchor || null;
    state.menuAnchor?.classList.add("is-open");
    return el;
  }

  function contextMenu(x, y, items) {
    return menu(items, x, y, { className: "axs-menu--context" });
  }

  document.addEventListener(
    "pointerdown",
    (event) => {
      if (!state.menuEl) return;
      if (state.menuEl.contains(event.target)) return;
      if (event.target.closest?.(".axs-menubar__btn")) return;
      closeMenu();
    },
    true,
  );

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });

  /* ── 窗口：按钮 / 拖拽区 / 缩放 ───────────────────────── */
  async function refreshFrame() {
    try {
      state.frame = (await axon().Axon.Window.frame()) || state.frame;
    } catch {
      /* 窗口关闭中 */
    }
    return state.frame;
  }

  async function toggleMaximize() {
    try {
      const maximized = await axon().Axon.Window.toggleMaximize();
      applyMaximized(maximized);
    } catch (err) {
      logError(err);
    }
  }

  function applyMaximized(maximized) {
    state.maximized = !!maximized;
    document.documentElement.dataset.axsMaximized = String(state.maximized);
    const btn = $("axsBtnMax");
    if (btn) {
      btn.dataset.state = state.maximized ? "maximized" : "normal";
      btn.innerHTML = state.maximized ? ICONS.restore : ICONS.max;
      btn.title = state.maximized ? "还原" : "最大化";
    }
    scheduleDragRegions();
    emit("state", { ...state, platform: state.platform });
  }

  function dragRect(bar) {
    const rect = bar.getBoundingClientRect();
    const blockers = [...bar.querySelectorAll("[data-axon-no-drag], button, input, a")].map((el) =>
      el.getBoundingClientRect(),
    );
    let segments = [[rect.left, rect.right]];
    for (const b of blockers) {
      if (!b.width || !b.height) continue;
      segments = segments.flatMap(([a, c]) => {
        if (b.right <= a || b.left >= c) return [[a, c]];
        const out = [];
        if (b.left > a) out.push([a, Math.min(b.left, c)]);
        if (b.right < c) out.push([Math.max(b.right, a), c]);
        return out;
      });
    }
    return segments
      .filter(([a, c]) => c - a > 4)
      .map(([a, c]) => ({ x: Math.round(a), y: Math.round(rect.top), w: Math.round(c - a), h: Math.round(rect.height) }));
  }

  async function reportDragRegions() {
    const bar = state.nativeHost?.querySelector(".axs-chrome");
    if (!bar || state.platform === "darwin") return;
    const regions = dragRect(bar);
    try {
      await axon().Axon.Window.setDragRegions(regions);
    } catch (err) {
      logError(err);
    }
  }

  let dragTimer = null;
  function scheduleDragRegions() {
    clearTimeout(dragTimer);
    dragTimer = setTimeout(reportDragRegions, 40);
  }

  function startMove(event) {
    const frame = { ...state.frame };
    const sx = event.screenX;
    const sy = event.screenY;
    let pending = null;
    const move = (e) => {
      pending = { x: frame.x + (e.screenX - sx), y: frame.y + (e.screenY - sy) };
      if (!move.raf) {
        move.raf = requestAnimationFrame(() => {
          move.raf = null;
          if (pending) axon().Axon.Window.moveTo(pending.x, pending.y).catch(() => {});
        });
      }
    };
    const up = () => {
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", up);
      refreshFrame();
    };
    addEventListener("pointermove", move);
    addEventListener("pointerup", up);
  }

  function startResize(event, edge, minSize) {
    event.preventDefault();
    (async () => {
      const frame = (await axon().Axon.Window.frame()) || state.frame;
      const sx = event.screenX;
      const sy = event.screenY;
      let pending = null;
      const move = (e) => {
        const dx = e.screenX - sx;
        const dy = e.screenY - sy;
        let { x, y, width, height } = frame;
        if (edge.includes("right")) width = Math.max(minSize[0], frame.width + dx);
        if (edge.includes("left")) {
          width = Math.max(minSize[0], frame.width - dx);
          x = frame.x + (frame.width - width);
        }
        if (edge.includes("bottom")) height = Math.max(minSize[1], frame.height + dy);
        if (edge.includes("top")) {
          height = Math.max(minSize[1], frame.height - dy);
          y = frame.y + (frame.height - height);
        }
        pending = { x, y, width, height };
        if (!move.raf) {
          move.raf = requestAnimationFrame(() => {
            move.raf = null;
            if (!pending) return;
            axon().Axon.Window.resizeTo(pending.width, pending.height).catch(() => {});
            axon().Axon.Window.moveTo(pending.x, pending.y).catch(() => {});
          });
        }
      };
      const up = () => {
        removeEventListener("pointermove", move);
        removeEventListener("pointerup", up);
        refreshFrame();
      };
      addEventListener("pointermove", move);
      addEventListener("pointerup", up);
    })();
  }

  /* 非 Windows：系统不做命中测试，网页自己补拖动与 8 向缩放 */
  function setupManualWindow(host, minSize) {
    const layer = document.createElement("div");
    layer.className = "axs-resize-layer";
    for (const edge of [
      "top",
      "bottom",
      "left",
      "right",
      "top-left",
      "top-right",
      "bottom-left",
      "bottom-right",
    ]) {
      const handle = document.createElement("div");
      handle.className = "axs-resize-handle";
      handle.dataset.edge = edge;
      handle.addEventListener("pointerdown", (event) => startResize(event, edge, minSize));
      layer.appendChild(handle);
    }
    document.body.appendChild(layer);

    const bar = host.querySelector(".axs-chrome");
    bar.addEventListener("pointerdown", async (event) => {
      if (event.button !== 0) return;
      if (event.target.closest("[data-axon-no-drag], button, input, a")) return;
      if (state.maximized) return;
      event.preventDefault();
      try {
        if (await axon().Axon.Window.beginSystemMove()) return;
      } catch {
        /* 落到手动拖动 */
      }
      startMove(event);
    });
    bar.addEventListener("dblclick", (event) => {
      if (event.target.closest("[data-axon-no-drag], button, input, a")) return;
      toggleMaximize();
    });
  }

  /* ── 原生菜单（Qt 弹的）──────────────────────────────── */
  function nativeMenu(spec) {
    return axon().Axon.Window.popupMenu(spec);
  }

  function onNativeMenu(cb) {
    state.listeners.nativeMenu.push(cb);
    return () => {
      state.listeners.nativeMenu = state.listeners.nativeMenu.filter((fn) => fn !== cb);
    };
  }

  /* ── 挂载 ─────────────────────────────────────────────── */
  function mount(options = {}) {
    const opts = {
      title: "",
      brand: "",
      menus: [],
      minSize: [760, 520],
      mount: null,
      onCommand: null,
      ...options,
    };

    initTheme();

    const host = document.createElement("div");
    host.className = "axs-host";
    const container = opts.mount
      ? typeof opts.mount === "string"
        ? document.querySelector(opts.mount)
        : opts.mount
      : document.body;
    if (!container) throw new Error("axon-shell: mount 容器不存在");
    if (container === document.body) document.body.appendChild(host);
    else container.appendChild(host);
    state.nativeHost = host;

    const chrome = document.createElement("header");
    chrome.className = "axs-chrome";
    chrome.setAttribute("data-axon-drag", "");
    chrome.innerHTML = `
      <div class="axs-brand" data-axon-no-drag>${opts.brand || ""}</div>
      <nav class="axs-menubar" data-axon-no-drag></nav>
      <div class="axs-title">${opts.title || ""}</div>
      <div class="axs-wbtns" data-axon-no-drag>
        <button class="axs-wbtn" id="axsBtnMin" title="最小化" type="button">${ICONS.min}</button>
        <button class="axs-wbtn" id="axsBtnMax" title="最大化" type="button">${ICONS.max}</button>
        <button class="axs-wbtn axs-wbtn--close" id="axsBtnClose" title="关闭" type="button">${ICONS.close}</button>
      </div>`;
    host.appendChild(chrome);
    document.documentElement.classList.add("axs-has-chrome");

    const menubar = chrome.querySelector(".axs-menubar");
    for (const group of opts.menus) {
      const btn = document.createElement("button");
      btn.className = "axs-menubar__btn";
      btn.type = "button";
      btn.textContent = group.label || group.id;
      btn.dataset.menu = group.id;
      btn.addEventListener("click", () => {
        const rect = btn.getBoundingClientRect();
        if (state.menuEl && state.menuAnchor === btn) {
          closeMenu();
          return;
        }
        menu(group.items || [], rect.left, rect.bottom + 2, {
          anchor: btn,
          className: "axs-menu--bar",
        });
      });
      menubar.appendChild(btn);
    }

    $("axsBtnMin").addEventListener("click", () => axon().Axon.Window.minimize().catch(logError));
    $("axsBtnMax").addEventListener("click", toggleMaximize);
    $("axsBtnClose").addEventListener("click", () => axon().Axon.Window.close().catch(logError));

    // 菜单命令的统一出口：没有 item.run 的项会走 onCommand
    state.listeners.command.push((item) => {
      if (typeof opts.onCommand === "function") opts.onCommand(item);
    });

    refreshFrame().then((frame) => {
      state.platform = state.platform || "linux";
      if (state.platform !== "win32" && state.platform !== "darwin") {
        setupManualWindow(host, opts.minSize);
      }
      scheduleDragRegions();
      emit("state", { ...state, frame });
    });

    addEventListener("resize", scheduleDragRegions);

    // Python 侧推来的窗口状态与原生菜单选中
    try {
      const { AxonEvent } = axon();
      AxonEvent.addListener("window:state", (payload) => {
        const data = payload || {};
        state.platform = data.platform || state.platform;
        state.frame = {
          x: data.x ?? state.frame.x,
          y: data.y ?? state.frame.y,
          width: data.width ?? state.frame.width,
          height: data.height ?? state.frame.height,
        };
        state.fullScreen = !!data.fullScreen;
        applyMaximized(!!data.maximized);
      });
      AxonEvent.addListener("window:menu", (payload) => {
        emit("nativeMenu", payload || {});
      });
    } catch (err) {
      logError(err);
    }

    const instance = {
      el: host,
      setTitle(text) {
        const node = chrome.querySelector(".axs-title");
        if (node) node.textContent = text;
        return axon().Axon.Window.setTitle(text);
      },
      refreshDragRegions: scheduleDragRegions,
      refreshFrame,
      openMenu: menu,
      contextMenu,
      closeMenu,
      nativeMenu,
      onState(cb) {
        state.listeners.state.push(cb);
        return () => {
          state.listeners.state = state.listeners.state.filter((fn) => fn !== cb);
        };
      },
      setTheme,
      toggleTheme,
      destroy() {
        closeMenu();
        host.remove();
        document.documentElement.classList.remove("axs-has-chrome");
      },
    };
    state.host = instance;

    // 拿到平台信息后决定要不要装手动缩放
    axon()
      .Axon.Window.platform()
      .then((platform) => {
        state.platform = platform;
        if (platform !== "win32" && platform !== "darwin" && !document.querySelector(".axs-resize-layer")) {
          setupManualWindow(host, opts.minSize);
        }
        scheduleDragRegions();
      })
      .catch(logError);

    return instance;
  }

  global.AxonShell = {
    mount,
    menu,
    contextMenu,
    closeMenu,
    nativeMenu,
    onNativeMenu,
    onState(cb) {
      state.listeners.state.push(cb);
      return () => {
        state.listeners.state = state.listeners.state.filter((fn) => fn !== cb);
      };
    },
    setTheme,
    toggleTheme,
    get theme() {
      return document.documentElement.dataset.axsTheme;
    },
    setTitle(text) {
      return state.host?.setTitle(text);
    },
    refreshFrame,
    get state() {
      return state;
    },
    icons: ICONS,
  };
})(window);
