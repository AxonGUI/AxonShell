# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [0.1.0] - 2026-11-24

从 `axon-gui` 里把这层「窗口外观」单独拆出来，成为一个可选依赖。

### 新增

- `AxonShellWindow`：无边框窗口，注册 `Axon.Window` 控制器；Windows 上接管 `WM_NCHITTEST`（标题栏 → `HTCAPTION`、边框 6px → `HTLEFT/...`），拖动、双击最大化、贴边、四向缩放都是系统行为；其它平台先试 `startSystemMove()`，再退化成指针增量。
- `window:state` / `window:menu` 两个前端事件：窗口状态变化、原生菜单选中。
- 前端皮肤 `assets/shell.css` + `assets/shell.js`：`AxonShell.mount()` 造标题栏、菜单条、窗口按钮；`menu()` / `contextMenu()` 画菜单；`nativeMenu()` 让 Qt 弹原生菜单；`setTheme()` / `toggleTheme()` 两套主题。
- `assets_dir()`：皮肤资源目录，交给静态服务即可。
- `examples/files`：文件浏览器示例（树、标签页、行号、编辑保存、输出面板、右键菜单、原生菜单）。
- `tests/verify.py`：15 条端到端断言（窗口状态、拖拽区、最大化/还原、缩放、网页菜单、右键菜单、编辑保存、原生菜单回传）。

### 说明

- 依赖 `axon-gui>=5.3.4`；通道、控制器、事件、Store 都不在这里。
- 从核心仓移除了 `core-py/axon/AxonWindow.py` 与 `examples/shell`：外观层不再跟核心耦合。
