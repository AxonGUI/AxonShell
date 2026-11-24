/* axon-shell runtime —— 只做「网页自己做不了」的那一层。
 *
 * 它不做任何视觉：没有标题栏、没有按钮、没有 CSS。标题栏长什么样、
 * 菜单放哪儿、按钮用什么图标，全部由你的 HTML/CSS 决定。
 *
 * 它提供四件事：
 *   1. 拖拽区上报：页面里标 data-axon-drag 的元素，其矩形（扣掉里面的
 *      按钮/输入框）会上报给 Qt。Windows 上这些矩形被当作 HTCAPTION，
 *      于是拖动、双击最大化、右键系统菜单都是系统原生行为。
 *   2. 窗口按钮接线：任何 [data-axon-window="min|max|close"] 点了就执行。
 *   3. 窗口状态与原生菜单事件：window:state / window:menu 转到 JS 回调。
 *   4. 兜底：Linux 上系统不做命中测试，这里补拖动与 8 向缩放。
 *
 * 用法：
 *   <script src="/vendor/axon.umd.cjs"></script>
 *   <script src="/axon-shell/shell.js"></script>
 *   <script>
 *     await AxonInit();                 // axon 自己的握手，见 axon-gui 文档
 *     AxonShell.init();                 // 接上拖拽区、窗口按钮、状态事件
 *   </script>
 */
(function (global) {
  "use strict";

  const doc = global.document;
  const root = () => doc.documentElement;

  const state = {
    ready: false,
    platform: "",
    frame: { x: 0, y: 0, width: 0, height: 0 },
    maximized: false,
    fullScreen: false,
    listeners: { state: [], menu: [] },
  };

  /* ── axon 库 ─────────────────────────────────────────────── */
  function lib() {
    const api = global.axon;
    if (!api) throw new Error("axon-shell: 先加载 axon 的产物（window.axon）");
    return api;
  }
  function win() {
    return lib().Axon.Window;
  }
  function logError(err) {
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

  /* ── 拖拽区：把 data-axon-drag 的矩形报给 Qt ─────────────── */
  function regions() {
    const out = [];
    for (const bar of doc.querySelectorAll("[data-axon-drag]")) {
      const rect = bar.getBoundingClientRect();
      if (!rect.width || !rect.height) continue;
      const holes = [];
      for (const el of bar.querySelectorAll(
        '[data-axon-no-drag], button, input, textarea, select, a, [role="button"]',
      )) {
        const r = el.getBoundingClientRect();
        if (r.width && r.height) holes.push(r);
      }
      // 一条横向长条，被里面的交互元素切成若干段
      let segments = [[rect.left, rect.right]];
      for (const b of holes) {
        segments = segments.flatMap(([a, c]) => {
          if (b.right <= a || b.left >= c) return [[a, c]];
          const cut = [];
          if (b.left > a) cut.push([a, Math.min(b.left, c)]);
          if (b.right < c) cut.push([Math.max(b.right, a), c]);
          return cut;
        });
      }
      for (const [a, c] of segments) {
        if (c - a <= 4) continue;
        out.push({
          x: Math.round(a),
          y: Math.round(rect.top),
          w: Math.round(c - a),
          h: Math.round(rect.height),
        });
      }
    }
    return out;
  }

  let dragTimer = null;
  function refreshDragRegions() {
    clearTimeout(dragTimer);
    dragTimer = setTimeout(async () => {
      try {
        await win().setDragRegions(regions());
      } catch (err) {
        logError(err);
      }
    }, 40);
  }

  /* ── 窗口状态 ───────────────────────────────────────────── */
  function applyState(data) {
    if (!data) return;
    state.platform = data.platform || state.platform;
    state.maximized = !!data.maximized;
    state.fullScreen = !!data.fullScreen;
    state.frame = {
      x: data.x ?? state.frame.x,
      y: data.y ?? state.frame.y,
      width: data.width ?? state.frame.width,
      height: data.height ?? state.frame.height,
    };
    root().dataset.axonMaximized = String(state.maximized);
    emit("state", snapshot());
    refreshDragRegions();
  }

  async function refreshState() {
    try {
      applyState(await win().state());
    } catch (err) {
      logError(err);
    }
    return state;
  }

  /* ── 窗口按钮：[data-axon-window="min|max|close"] ────────── */
  function action(name) {
    if (name === "min") return win().minimize();
    if (name === "max") return win().toggleMaximize().then((v) => applyState({ maximized: v }));
    if (name === "close") return win().close();
    return Promise.resolve();
  }

  function bindControls(target) {
    target.addEventListener("click", (event) => {
      const el = event.target.closest("[data-axon-window]");
      if (!el || !target.contains(el)) return;
      event.preventDefault();
      action(el.dataset.axonWindow).catch(logError);
    });
  }

  /* ── 非 Windows / macOS：系统不做命中测试，这里补 ────────── */
  function enableFallback() {
    const bar = () => doc.querySelector("[data-axon-drag]");
    let frame = null;
    let dragging = false;

    async function beginDrag(event) {
      if (event.button !== 0) return;
      if (state.maximized || !bar()) return;
      const hit = event.target.closest(
        '[data-axon-no-drag], button, input, textarea, select, a, [role="button"]',
      );
      if (hit) return;
      event.preventDefault();
      try {
        if (await win().beginSystemMove()) return;
      } catch {
        /* 系统不支持，走手动 */
      }
      frame = (await win().frame()) || state.frame;
      const sx = event.screenX;
      const sy = event.screenY;
      let pending = null;
      dragging = true;
      const move = (e) => {
        pending = { x: frame.x + (e.screenX - sx), y: frame.y + (e.screenY - sy) };
        if (move.raf) return;
        move.raf = requestAnimationFrame(() => {
          move.raf = null;
          if (pending) win().moveTo(pending.x, pending.y).catch(() => {});
        });
      };
      const up = () => {
        dragging = false;
        removeEventListener("pointermove", move);
        removeEventListener("pointerup", up);
        refreshState();
      };
      addEventListener("pointermove", move);
      addEventListener("pointerup", up);
    }

    doc.addEventListener("pointerdown", (event) => {
      if (dragging) return;
      const zone = event.target.closest("[data-axon-drag]");
      if (zone) beginDrag(event);
    });
    doc.addEventListener("dblclick", (event) => {
      const zone = event.target.closest("[data-axon-drag]");
      if (!zone) return;
      if (event.target.closest('[data-axon-no-drag], button, input, textarea, select, a')) return;
      win()
        .toggleMaximize()
        .then((v) => applyState({ maximized: v }))
        .catch(logError);
    });

    // 8 向缩放的透明命中条（只是热区，不是视觉）
    if (!doc.querySelector("[data-axon-resize]")) {
      const layer = doc.createElement("div");
      layer.dataset.axonResize = "1";
      Object.assign(layer.style, {
        position: "fixed",
        inset: "0",
        pointerEvents: "none",
        zIndex: "2147483647",
      });
      const edges = [
        ["top", "top:0;left:0;right:0;height:5px;cursor:ns-resize"],
        ["bottom", "bottom:0;left:0;right:0;height:5px;cursor:ns-resize"],
        ["left", "left:0;top:0;bottom:0;width:5px;cursor:ew-resize"],
        ["right", "right:0;top:0;bottom:0;width:5px;cursor:ew-resize"],
        ["top-left", "top:0;left:0;width:10px;height:10px;cursor:nwse-resize"],
        ["top-right", "top:0;right:0;width:10px;height:10px;cursor:nesw-resize"],
        ["bottom-left", "bottom:0;left:0;width:10px;height:10px;cursor:nesw-resize"],
        ["bottom-right", "bottom:0;right:0;width:10px;height:10px;cursor:nwse-resize"],
      ];
      for (const [edge, css] of edges) {
        const handle = doc.createElement("div");
        handle.dataset.axonResizeEdge = edge;
        handle.style.cssText = "position:absolute;pointer-events:auto;" + css;
        handle.addEventListener("pointerdown", (event) => beginResize(event, edge));
        layer.appendChild(handle);
      }
      doc.body.appendChild(layer);
    }

    async function beginResize(event, edge) {
      event.preventDefault();
      const start = (await win().frame()) || state.frame;
      const sx = event.screenX;
      const sy = event.screenY;
      let pending = null;
      const move = (e) => {
        const dx = e.screenX - sx;
        const dy = e.screenY - sy;
        let { x, y, width, height } = start;
        if (edge.includes("right")) width = Math.max(480, start.width + dx);
        if (edge.includes("left")) {
          width = Math.max(480, start.width - dx);
          x = start.x + (start.width - width);
        }
        if (edge.includes("bottom")) height = Math.max(320, start.height + dy);
        if (edge.includes("top")) {
          height = Math.max(320, start.height - dy);
          y = start.y + (start.height - height);
        }
        pending = { x, y, width, height };
        if (move.raf) return;
        move.raf = requestAnimationFrame(() => {
          move.raf = null;
          if (!pending) return;
          win().resizeTo(pending.width, pending.height).catch(() => {});
          win().moveTo(pending.x, pending.y).catch(() => {});
        });
      };
      const up = () => {
        removeEventListener("pointermove", move);
        removeEventListener("pointerup", up);
        refreshState();
      };
      addEventListener("pointermove", move);
      addEventListener("pointerup", up);
    }
  }

  /* ── 原生菜单：交给 Qt 画 ───────────────────────────────── */
  function nativeMenu(spec, opts) {
    const options = opts || {};
    return win()
      .popupMenu(spec, options.x, options.y)
      .then((requestId) => requestId);
  }

  /* ── 初始化 ─────────────────────────────────────────────── */
  function init(options) {
    const opts = options || {};
    if (state.ready) {
      refreshDragRegions();
      return snapshot();
    }
    state.ready = true;

    if (opts.controls !== false) bindControls(doc);

    try {
      const { AxonEvent } = lib();
      AxonEvent.addListener("window:state", (payload) => applyState(payload || {}));
      AxonEvent.addListener("window:menu", (payload) => emit("menu", payload || {}));
    } catch (err) {
      logError(err);
    }

    addEventListener("resize", refreshDragRegions);
    // 页面布局稳定后（字体、图片）再报一次
    setTimeout(refreshDragRegions, 120);

    refreshState()
      .then(() => win().platform())
      .then((platform) => {
        state.platform = platform;
        if (platform !== "win32" && platform !== "darwin" && opts.fallback !== false) {
          enableFallback();
        }
        refreshDragRegions();
        emit("state", snapshot());
      })
      .catch(logError);

    return state;
  }

  function snapshot() {
    return {
      platform: state.platform,
      frame: { ...state.frame },
      maximized: state.maximized,
      fullScreen: state.fullScreen,
    };
  }

  global.AxonShell = {
    init,
    drag: { refresh: refreshDragRegions, regions },
    window: {
      state: snapshot,
      refresh: refreshState,
      minimize: () => win().minimize(),
      toggleMaximize: () => win().toggleMaximize().then((v) => applyState({ maximized: v })),
      close: () => win().close(),
      setTitle: (text) => win().setTitle(text),
      setAlwaysOnTop: (on) => win().setAlwaysOnTop(on),
      frame: () => win().frame(),
      onState(cb) {
        state.listeners.state.push(cb);
        return () => {
          state.listeners.state = state.listeners.state.filter((fn) => fn !== cb);
        };
      },
    },
    menu: {
      native: nativeMenu,
      onSelect(cb) {
        state.listeners.menu.push(cb);
        return () => {
          state.listeners.menu = state.listeners.menu.filter((fn) => fn !== cb);
        };
      },
    },
    get state() {
      return state;
    },
  };
})(window);
