/* 文件浏览器示例：这一份代码里没有一帧窗口外观，也没有一行 Qt。
 *
 * 外壳（标题栏 / 菜单 / 窗口按钮 / 拖拽区 / 缩放 / 右键菜单）来自 /axon-shell/shell.js，
 * 窗口控制走 Axon.Window.*，文件读写走 Axon.Files.*。
 */

const { Axon, AxonInit } = window.axon;

const $ = (id) => document.getElementById(id);

const state = {
  connected: false,
  platform: "linux",
  frame: { x: 0, y: 0, width: 0, height: 0 },
  tabs: [],
  activeTab: null,
  tree: null,
  selected: null,
  shell: null,
};

/* ── 输出面板 ─────────────────────────────────────────── */
function log(kind, text) {
  const li = document.createElement("li");
  const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  li.innerHTML = `<span class="t">${time}</span><span class="k-${kind}"></span>`;
  li.lastChild.textContent = text;
  const box = $("log");
  box.appendChild(li);
  box.scrollTop = box.scrollHeight;
}

/* ── 菜单 ─────────────────────────────────────────────── */
const MENUS = [
  {
    id: "file",
    label: "文件",
    items: [
      { id: "newFile", label: "新建文件", shortcut: "Ctrl+N", run: () => promptCreate("file") },
      { id: "newDir", label: "新建文件夹", shortcut: "Ctrl+Shift+N", run: () => promptCreate("dir") },
      { kind: "separator" },
      { id: "save", label: "保存", shortcut: "Ctrl+S", run: () => saveActive() },
      { id: "reload", label: "从磁盘重新载入", run: () => reloadActive() },
      { kind: "separator" },
      { id: "reveal", label: "在文件管理器中显示", run: () => revealActive() },
      { kind: "separator" },
      { id: "quit", label: "退出", shortcut: "Alt+F4", run: () => Axon.Window.close() },
    ],
  },
  {
    id: "view",
    label: "视图",
    items: [
      {
        id: "sidebar",
        label: "显示侧边栏",
        kind: "check",
        checked: () => document.documentElement.dataset.sidebar !== "hidden",
        run: () => toggleAttr("sidebar"),
      },
      {
        id: "panel",
        label: "显示输出面板",
        kind: "check",
        checked: () => document.documentElement.dataset.panel !== "hidden",
        run: () => toggleAttr("panel"),
      },
      { kind: "separator" },
      {
        id: "theme",
        label: "浅色主题",
        kind: "check",
        checked: () => document.documentElement.dataset.axsTheme === "light",
        run: () => {
          const theme = AxonShell.toggleTheme();
          renderStatus();
          log("window", `主题切换为 ${theme === "light" ? "浅色" : "深色"}`);
        },
      },
      { kind: "separator" },
      { id: "fullscreen", label: "切换全屏", shortcut: "F11", run: () => Axon.Window.toggleFullScreen() },
    ],
  },
  {
    id: "window",
    label: "窗口",
    items: [
      { id: "min", label: "最小化", run: () => Axon.Window.minimize() },
      {
        id: "max",
        label: "最大化 / 还原",
        kind: "check",
        checked: () => state.maximized === true,
        run: () => Axon.Window.toggleMaximize(),
      },
      { kind: "separator" },
      {
        id: "ontop",
        label: "窗口置顶",
        kind: "check",
        checked: () => state.alwaysOnTop === true,
        run: async () => {
          state.alwaysOnTop = !state.alwaysOnTop;
          await Axon.Window.setAlwaysOnTop(state.alwaysOnTop);
          log("window", `置顶：${state.alwaysOnTop ? "开" : "关"}`);
        },
      },
      { kind: "separator" },
      {
        id: "native",
        label: "原生菜单（Qt 弹出）",
        run: () => demoNativeMenu(),
      },
      { kind: "separator" },
      { id: "close", label: "关闭窗口", run: () => Axon.Window.close() },
    ],
  },
  {
    id: "help",
    label: "帮助",
    items: [
      { id: "docs", label: "axon-shell 文档", run: () => window.open("https://github.com/AxonGUI/AxonShell", "_blank") },
      { id: "about", label: "关于", run: () => showAbout() },
    ],
  },
];

/* ── 文件树 ───────────────────────────────────────────── */
const FILE_ICON = '<svg viewBox="0 0 16 16"><path d="M4 2.5h5l3 3v8H4z"/><path d="M9 2.5v3h3"/></svg>';
const DIR_ICON = '<svg viewBox="0 0 16 16"><path d="M2 4.5h4l1.2 1.4H14v7.6H2z"/></svg>';

async function loadTree(root = "") {
  try {
    state.tree = await Axon.Files.list_dir(root);
    renderTree();
    log("py", `list_dir "${root || "/"}" → ${state.tree.entries.length} 项`);
  } catch (err) {
    log("error", `读取目录失败：${msg(err)}`);
  }
}

function renderTree() {
  const box = $("tree");
  box.innerHTML = "";
  if (!state.tree?.entries?.length) {
    box.innerHTML = '<div class="tree__empty">这个目录是空的。用「文件 → 新建文件」加一个。</div>';
    return;
  }
  for (const entry of state.tree.entries) {
    box.appendChild(treeRow(entry, 0));
  }
  refreshShellState();
}

function treeRow(entry, depth) {
  const row = document.createElement("div");
  row.className = "tree__row";
  row.dataset.path = entry.path;
  row.dataset.dir = String(entry.isDir);
  row.style.setProperty("--depth", depth);
  row.innerHTML = `
    <span class="caret">${entry.isDir ? "▸" : ""}</span>
    <span class="ico">${entry.isDir ? DIR_ICON : FILE_ICON}</span>
    <span class="name"></span>`;
  row.querySelector(".name").textContent = entry.name;

  if (entry.isDir) {
    let loaded = false;
    row.querySelector(".caret").addEventListener("click", async (event) => {
      event.stopPropagation();
      await toggleDir(entry.path, row, loaded);
      loaded = !loaded;
    });
  }

  row.addEventListener("click", async () => {
    state.selected = entry.path;
    for (const el of document.querySelectorAll(".tree__row.is-selected")) el.classList.remove("is-selected");
    row.classList.add("is-selected");
    if (entry.isDir) {
      await loadTree(entry.path);
    } else {
      await openFile(entry.path);
    }
  });

  row.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    state.selected = entry.path;
    AxonShell.contextMenu(event.clientX, event.clientY, treeMenu(entry));
  });

  return row;
}

async function toggleDir(path, row, loaded) {
  const next = row.nextElementSibling;
  if (loaded && next?.dataset.depth === "child") {
    while (row.nextElementSibling?.dataset.depth === "child") row.nextElementSibling.remove();
    row.querySelector(".caret").textContent = "▸";
    return;
  }
  try {
    const listing = await Axon.Files.list_dir(path);
    const depth = Number(row.style.getPropertyValue("--depth") || 0) + 1;
    let anchor = row;
    for (const child of listing.entries) {
      const childRow = treeRow(child, depth);
      childRow.dataset.depth = "child";
      anchor.after(childRow);
      anchor = childRow;
    }
    row.querySelector(".caret").textContent = "▾";
    log("py", `展开 ${path} → ${listing.entries.length} 项`);
  } catch (err) {
    log("error", `展开失败：${msg(err)}`);
  }
}

function treeMenu(entry) {
  return [
    entry.isDir
      ? { id: "open", label: "展开 / 收起", run: () => loadTree(entry.path) }
      : { id: "open", label: "打开", run: () => openFile(entry.path) },
    { kind: "separator" },
    { id: "newFile", label: "在此新建文件", run: () => promptCreate("file", entry.isDir ? entry.path : parentOf(entry.path)) },
    { id: "newDir", label: "在此新建文件夹", run: () => promptCreate("dir", entry.isDir ? entry.path : parentOf(entry.path)) },
    { kind: "separator" },
    { id: "rename", label: "重命名", run: () => promptRename(entry.path) },
    { id: "copy", label: "复制相对路径", run: () => copyText(entry.path) },
    { id: "reveal", label: "在文件管理器中显示", run: () => Axon.Files.reveal(entry.path) },
    { kind: "separator" },
    { id: "delete", label: "删除", run: () => removePath(entry.path) },
  ];
}

const parentOf = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

/* ── 标签页与编辑区 ───────────────────────────────────── */
async function openFile(path) {
  const existing = state.tabs.find((tab) => tab.path === path);
  if (existing) {
    activateTab(path);
    return;
  }
  try {
    const file = await Axon.Files.read_file(path);
    state.tabs.push({ path, name: path.split("/").pop(), content: file.content, dirty: false });
    activateTab(path);
    log("py", `read_file "${path}" → ${file.content.length} 字符`);
  } catch (err) {
    log("error", `打开失败：${msg(err)}`);
  }
}

function activateTab(path) {
  state.activeTab = path;
  const tab = state.tabs.find((item) => item.path === path);
  const wrap = $("editWrap");
  const area = $("codearea");
  if (!tab) {
    wrap.hidden = true;
    $("placeholder").hidden = false;
    renderTabs();
    return;
  }
  wrap.hidden = false;
  $("placeholder").hidden = true;
  area.value = tab.content;
  renderTabs();
  renderGutter();
  renderStatus();
  area.focus();
}

function renderTabs() {
  const box = $("tabs");
  box.innerHTML = "";
  for (const tab of state.tabs) {
    const el = document.createElement("div");
    el.className = "tab" + (tab.path === state.activeTab ? " is-active" : "");
    el.innerHTML = `<span class="name"></span>${tab.dirty ? '<span class="dirty"></span>' : ""}<button class="x" title="关闭">×</button>`;
    el.querySelector(".name").textContent = tab.name;
    el.addEventListener("click", (event) => {
      if (event.target.classList.contains("x")) {
        closeTab(tab.path);
      } else {
        activateTab(tab.path);
      }
    });
    el.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      AxonShell.contextMenu(event.clientX, event.clientY, [
        { id: "close", label: "关闭", run: () => closeTab(tab.path) },
        { id: "others", label: "关闭其他", run: () => closeOthers(tab.path) },
        { kind: "separator" },
        { id: "copy", label: "复制路径", run: () => copyText(tab.path) },
      ]);
    });
    box.appendChild(el);
  }
}

function closeTab(path) {
  state.tabs = state.tabs.filter((tab) => tab.path !== path);
  if (state.activeTab === path) state.activeTab = state.tabs.at(-1)?.path ?? null;
  activateTab(state.activeTab);
}

function closeOthers(path) {
  state.tabs = state.tabs.filter((tab) => tab.path === path);
  activateTab(path);
}

function renderGutter() {
  const lines = ($("codearea").value.match(/\n/g)?.length ?? 0) + 1;
  $("gutter").textContent = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
  $("gutter").scrollTop = $("codearea").scrollTop;
}

async function saveActive() {
  const tab = state.tabs.find((item) => item.path === state.activeTab);
  if (!tab) {
    log("window", "没有打开的文件");
    return;
  }
  try {
    const result = await Axon.Files.write_file(tab.path, $("codearea").value);
    tab.content = $("codearea").value;
    tab.dirty = false;
    renderTabs();
    log("py", `write_file "${tab.path}" → ${result.bytes} 字节`);
  } catch (err) {
    log("error", `保存失败：${msg(err)}`);
  }
}

async function reloadActive() {
  const tab = state.tabs.find((item) => item.path === state.activeTab);
  if (!tab) return;
  const file = await Axon.Files.read_file(tab.path);
  tab.content = file.content;
  tab.dirty = false;
  activateTab(tab.path);
  log("py", `重新载入 "${tab.path}"`);
}

function revealActive() {
  const tab = state.tabs.find((item) => item.path === state.activeTab);
  if (tab) Axon.Files.reveal(tab.path).catch((err) => log("error", msg(err)));
}

/* ── 新建 / 重命名 / 删除 ─────────────────────────────── */
async function promptCreate(kind, dirPath = null) {
  const base = dirPath ?? (state.selected && !state.selected.includes(".") ? state.selected : "");
  const name = window.prompt(kind === "dir" ? "新文件夹名字" : "新文件名");
  if (!name) return;
  try {
    const entry = kind === "dir"
      ? await Axon.Files.create_dir(base, name)
      : await Axon.Files.create_file(base, name);
    log("py", `创建 ${entry.path}`);
    await loadTree(state.tree?.path ?? "");
  } catch (err) {
    log("error", `创建失败：${msg(err)}`);
  }
}

async function promptRename(path) {
  const name = window.prompt("重命名为", path.split("/").pop());
  if (!name) return;
  try {
    const entry = await Axon.Files.rename(path, name);
    log("py", `重命名 → ${entry.path}`);
    await loadTree(state.tree?.path ?? "");
  } catch (err) {
    log("error", `重命名失败：${msg(err)}`);
  }
}

async function removePath(path) {
  if (!window.confirm(`删除 ${path}？`)) return;
  try {
    await Axon.Files.delete(path);
    state.tabs = state.tabs.filter((tab) => tab.path !== path);
    activateTab(state.tabs.at(-1)?.path ?? null);
    await loadTree(state.tree?.path ?? "");
    log("py", `删除 ${path}`);
  } catch (err) {
    log("error", `删除失败：${msg(err)}`);
  }
}

/* ── 原生菜单 / 关于 / 杂项 ───────────────────────────── */
async function demoNativeMenu() {
  const requestId = await AxonShell.nativeMenu({
    title: "原生菜单由 Qt 绘制",
    items: [
      { id: "alpha", label: "第一个" },
      { id: "beta", label: "第二个", enabled: false },
      { kind: "separator" },
      { id: "gamma", label: "第三个" },
    ],
  });
  log("window", `已弹出原生菜单 ${requestId}，等你在系统菜单里点一项`);
}

async function showAbout() {
  const info = await Axon.Files.about();
  log("window", `axon-shell 示例 · Python ${info.python} · Qt ${info.qt} · ${info.platform}`);
  window.alert(`axon-shell 文件浏览器\n\nPython ${info.python}\nQt ${info.qt}\n平台 ${info.platform}\n工作区 ${info.workspace}`);
}

function toggleAttr(name) {
  const root = document.documentElement;
  root.dataset[name] = root.dataset[name] === "hidden" ? "" : "hidden";
}

function copyText(text) {
  navigator.clipboard?.writeText(text).then(
    () => log("window", `已复制：${text}`),
    () => log("error", "复制失败"),
  );
}

const msg = (err) => err?.message || String(err);

/* ── 状态栏 ───────────────────────────────────────────── */
function renderStatus() {
  const tab = state.tabs.find((item) => item.path === state.activeTab);
  $("stPath").textContent = tab ? tab.path : state.tree?.path ? `/${state.tree.path}` : "/";
  $("stTheme").textContent = document.documentElement.dataset.axsTheme === "light" ? "浅色" : "深色";
  $("stFrame").textContent = `${state.frame.width}×${state.frame.height}`;
  $("stConn").textContent = state.connected ? "已连接 Python 后端" : "未连接后端";
  document.querySelector(".statusbar").classList.toggle("is-offline", !state.connected);
}

function renderPos() {
  const area = $("codearea");
  const before = area.value.slice(0, area.selectionStart);
  const line = before.split("\n").length;
  const col = before.length - before.lastIndexOf("\n");
  $("stPos").textContent = `Ln ${line}, Col ${col}`;
}

function refreshShellState() {
  globalThis.__files = {
    connected: state.connected,
    chrome: !!document.querySelector(".axs-chrome"),
    rows: document.querySelectorAll(".tree__row").length,
    platform: state.platform,
    theme: document.documentElement.dataset.axsTheme,
  };
}

/* ── 启动 ─────────────────────────────────────────────── */
async function boot() {
  const status = await AxonInit();
  state.connected = status.ready === true;
  state.platform = detectPlatform();

  state.shell = AxonShell.mount({
    title: "Files · axon-shell",
    brand: '<img src="/brand.svg" alt="Axon" />',
    menus: MENUS,
    minSize: [880, 560],
    onCommand: (item) => log("window", `菜单命令：${item.id}`),
  });

  state.shell.onState((snapshot) => {
    state.frame = snapshot.frame || state.frame;
    state.maximized = snapshot.maximized;
    renderStatus();
  });

  AxonShell.onNativeMenu((payload) => {
    globalThis.__files = { ...(globalThis.__files || {}), lastMenu: payload };
    log("window", `原生菜单选中：${payload.id}（请求 ${payload.requestId}）`);
  });

  setInterval(async () => {
    try {
      state.frame = (await Axon.Window.frame()) || state.frame;
      renderStatus();
    } catch {
      /* 窗口关闭中 */
    }
  }, 1000);

  const area = $("codearea");
  area.addEventListener("input", () => {
    const tab = state.tabs.find((item) => item.path === state.activeTab);
    if (!tab) return;
    tab.dirty = tab.content !== area.value;
    renderTabs();
    renderGutter();
  });
  area.addEventListener("keyup", renderPos);
  area.addEventListener("click", renderPos);
  area.addEventListener("scroll", () => ($("gutter").scrollTop = area.scrollTop));
  document.addEventListener("keydown", (event) => {
    const mod = event.ctrlKey || event.metaKey;
    if (!mod) return;
    if (event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveActive();
    }
    if (event.key.toLowerCase() === "n") {
      event.preventDefault();
      promptCreate("file");
    }
  });
  $("btnClear").addEventListener("click", () => ($("log").innerHTML = ""));
  $("btnRoot").addEventListener("click", () => loadTree(""));

  log("window", `外壳已挂载（platform=${state.platform}，后端${state.connected ? "已连接" : "未连接"}）`);
  await loadTree("");
  renderStatus();
  refreshShellState();
}

function detectPlatform() {
  const ua = navigator.userAgent;
  if (ua.includes("Windows")) return "win32";
  if (ua.includes("Mac")) return "darwin";
  return "linux";
}

boot().catch((err) => log("error", `启动失败：${msg(err)}`));
