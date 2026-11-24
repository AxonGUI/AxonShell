# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [0.2.1] - 2026-11-24

### 修复

- `examples/basic/main.py`：标题栏品牌图改成多级查找（`AXON_BRAND` → 打包目录 → 仓库 `assets/` → 包内
  `icon-256.png`），按扩展名给 Content-Type。以前在「把示例目录拷到别处、只 `pip install axon-shell`」
  这种真实用法下会抛 `FileNotFoundError: /tmp/assets/axon-mark.svg`（示例能跑，但启动时打一段 traceback）。

### 变更

- CI 改成从 PyPI 装 `axon-gui==5.3.4`（不再依赖 Release 上的 wheel 链接），顺带验证「框架在 PyPI 上」这条路。
- 新增 `.github/workflows/publish-pypi.yml`：Trusted Publishing（OIDC），`workflow_dispatch` 触发。

## [0.2.0] - 2026-11-24

收缩成「只做网页做不了的那层」。纯前端的部分（标题栏、菜单条、窗口按钮样式、主题、右键菜单面板）
全部删掉——这些应该由使用者自己写。

### 变更

- `assets/shell.js` 重写成薄库：不再生成任何 DOM、不再带 CSS。
  - `AxonShell.init()`：接 `data-axon-window` 点击、扫 `[data-axon-drag]` 上报拖动区、订阅
    `window:state` / `window:menu`、在 `<html>` 打 `data-axon-platform` 与 `data-axon-maximized`。
  - `AxonShell.drag.refresh()/regions()`；`window.state()/minimize()/toggleMaximize()/close()/`
    `setTitle()/setAlwaysOnTop()/refresh()/onState()`；`menu.native(spec)` / `menu.onSelect(cb)`。
  - `enableFallback()`：非 Windows/macOS 上补指针拖动与八向缩放。
- 窗口状态导出改为纯数据 `{platform, frame, maximized, fullScreen}`。
- `popupMenu(spec, x, y)` 支持坐标锚点（省略时用鼠标位置）。
- 示例 `examples/files`（含 500 行 VSCode 仿制）换成 `examples/basic`：一条 `data-axon-drag`
  顶栏 + 三个 `data-axon-window` 按钮 + 三行演示按钮，样式由示例自己写。
- `tests/verify.py` 缩到 11 条：拖拽区、按钮最大化/还原、状态、缩放、Python 往返、原生菜单。
- README / README.en 重写，明确「不含任何界面」。

### 移除

- `assets/shell.css`（262 行）与 `AxonShell.mount()` / `menu()` / `contextMenu()` /
  `nativeMenu()` / `setTheme()` / `toggleTheme()` 等皮肤 API。
- `examples/files` 及其工作区。

## [0.1.0] - 2026-11-24

从 `axon-gui` 里把这层「窗口外观」单独拆出来，成为一个可选依赖。

### 新增

- `AxonShellWindow`：无边框窗口，注册 `Axon.Window` 控制器；Windows 上接管 `WM_NCHITTEST`（标题栏 → `HTCAPTION`、边框 6px → `HTLEFT/...`），拖动、双击最大化、贴边、四向缩放都是系统行为；其它平台先试 `startSystemMove()`，再退化成指针增量。
- `window:state` / `window:menu` 两个前端事件：窗口状态变化、原生菜单选中。
- 前端皮肤 `assets/shell.css` + `assets/shell.js`（0.2.0 已移除纯前端部分）。
- `assets_dir()`：资源目录，交给静态服务即可。
- `tests/verify.py`：端到端断言。
