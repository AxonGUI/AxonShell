<p align="center">
  <img src="assets/axon-mark.svg" width="72" alt="Axon" />
</p>

# axon-shell

Window chrome for [Axon](https://github.com/AxonGUI/Axon) apps: a frameless window, a custom title bar, a menu bar, window buttons, HTML context menus — and on Windows, native hit-testing so dragging, double-click-to-maximize, snap and eight-way resizing stay system behaviour.

This is not the framework core. Channels, controllers, events and stores live in `axon-gui`; this package only owns the look, and can be dropped without touching the core.

<sub>[简体中文](README.md) · English</sub>

---

## Why

An `AxonGUI` window is a **normal system window**: OS title bar, OS buttons, OS border. Making it feel like VSCode / Electron takes three things:

1. a window that paints no system chrome (`FramelessWindowHint`) — otherwise your title bar sits under a system one;
2. dragging, double-click maximize, screen-edge snap and eight-way resize still working — on Windows that means answering `WM_NCHITTEST`;
3. a front-end skin: title bar, menus, window buttons, context menus.

All three live here. Your app code contains no Qt.

## Install

```bash
pip install axon-shell          # once it is on PyPI
pip install "git+https://github.com/AxonGUI/AxonShell.git"   # for now
```

Depends on `axon-gui` (which brings PySide6).

## Thirty-second setup

**Python** — swap the window class:

```python
import sys
from PySide6.QtWidgets import QApplication
from axon import AxonController, AxonMagicGUI
from axon_shell import AxonShellWindow

WEB = "MainView"

@AxonController(WEB, id="App")
class App:
    def hello(self, name: str) -> str:
        return f"Hello, {name}"

def main() -> int:
    app = QApplication(sys.argv[:1])
    AxonMagicGUI()
    window = AxonShellWindow(WEB, "http://127.0.0.1:8000/", title="My App")
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
```

**Page** — load the skin, then mount:

```html
<link rel="stylesheet" href="/axon-shell/shell.css" />
<script src="/axon.umd.cjs"></script>
<script src="/axon-shell/shell.js"></script>
<script>
  const { AxonInit } = window.axon;

  (async () => {
    await AxonInit();
    AxonShell.mount({
      title: "My App",
      menus: [{
        id: "file", label: "File", items: [
          { id: "new", label: "New", shortcut: "Ctrl+N", run: () => {} },
          { kind: "separator" },
          { id: "quit", label: "Quit", run: () => Axon.Window.close() },
        ],
      }],
    });
  })();
</script>
```

Serve the assets with `assets_dir()`:

```python
from axon_shell import assets_dir
print(assets_dir())   # mount it at /axon-shell/
```

## What you get

| Surface | Names |
| --- | --- |
| Python | `AxonShellWindow(...)`, `assets_dir()` |
| `Axon.Window` controller | `minimize / maximize / restore / toggleMaximize / toggleFullScreen / close / setAlwaysOnTop / setTitle / setDragRegions / beginSystemMove / moveTo / resizeTo / moveBy / frame / state / platform / popupMenu / closeMenu` |
| Events | `window:state`, `window:menu` |
| `window.AxonShell` | `mount`, `menu`, `contextMenu`, `nativeMenu`, `onNativeMenu`, `setTheme`, `toggleTheme`, `setTitle`, `refreshFrame`, `onState` |

Menu items accept `id/label/shortcut/kind ("check" | "separator")/checked/disabled/items/run`.

## Per-platform window behaviour

- **Windows**: Python answers `WM_NCHITTEST` — the title bar (minus `[data-axon-no-drag]`) reports `HTCAPTION`, the six-pixel border reports `HTLEFT/...`, so dragging, snap, double-click maximize and resizing are all native.
- **Linux / macOS**: `startSystemMove()` when available; otherwise a pointer-delta fallback with eight `.axs-resize-handle` edges.

Mark draggable areas in HTML:

```html
<header data-axon-drag>
  <nav data-axon-no-drag><button>File</button></nav>
</header>
```

## Demo

`examples/files/` is a file browser: tree, tabs, line numbers, edit-and-save, output panel, HTML context menus, native menu. All chrome comes from this package.

```bash
cd examples/files
python main.py --smoke
python ../../tests/verify.py
```

MIT © STofone
