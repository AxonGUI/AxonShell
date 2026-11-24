<p align="center">
  <img src="assets/axon-mark.svg" width="72" alt="Axon" />
</p>

# axon-shell

The part of a desktop window that a web page **cannot** do, for [Axon](https://github.com/AxonGUI/Axon) apps: frameless window, draggable regions, native window buttons, window-state events, and a bridge for native menus.

This package ships **no UI at all** — no title bar, no menu bar, no button styles, no theme, not a single line of CSS. What your title bar looks like is your business; this only makes it actually draggable, minimizable and closeable.

<sub>[简体中文](README.md) · English</sub>

---

## Why it exists

Three things a browser cannot do, and they are exactly the three that need Python:

1. **A frameless window** — drop the OS title bar, own the whole surface;
2. **Dragging and resizing still work** — on Windows you must answer `WM_NCHITTEST` with `HTCAPTION`, which is what gives you real dragging, double-click maximize, edge snapping and border resizing; on Linux/macOS it falls back to `startSystemMove()` plus pointer deltas;
3. **Window control** — minimize / maximize / restore / close / always-on-top / resize, plus a "state changed" event.

Everything else is frontend work. So this package is small on purpose: you can always drop it and call `Axon.Window` yourself.

<p align="center"><img src="assets/screenshot.png" alt="Example: one draggable bar and three window buttons" width="760"></p>

## Install

Neither `axon-gui` nor `axon-shell` is on PyPI yet (once it is, it is two `pip install` lines):

```bash
# 1) the framework: wheel from the release (brings PySide6)
pip install "https://github.com/AxonGUI/Axon/releases/download/v5.3.4/axon_gui-5.3.4-py3-none-any.whl"

# 2) the shell. --no-deps: axon-gui is not on PyPI, dependency resolution would 404
pip install --no-deps "git+https://github.com/AxonGUI/AxonShell.git"
```

## Thirty seconds

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
        return f"hello, {name}"

def main() -> int:
    app = QApplication(sys.argv[:1])
    AxonMagicGUI()
    window = AxonShellWindow(WEB, "http://127.0.0.1:8000/", title="My App")
    window.show()
    return app.exec()

raise SystemExit(main())
```

**Page** — write your own title bar, mark two attributes, done:

```html
<script src="/axon.umd.cjs"></script>          <!-- axon-gui UMD build -->
<script src="/axon-shell/shell.js"></script>   <!-- the only JS file in this package -->

<header data-axon-drag>                        <!-- this area drags the window -->
  <span>My App</span>
  <button data-axon-window="min">–</button>    <!-- wiring is automatic -->
  <button data-axon-window="max">□</button>
  <button data-axon-window="close">×</button>
</header>

<script>
  (async () => {
    await window.axon.AxonInit();
    window.AxonShell.init();
    window.AxonShell.window.onState(s => console.log(s.frame));
  })();
</script>
```

Serve `shell.js` from the package:

```python
from axon_shell import assets_dir
print(assets_dir())   # .../axon_shell/assets
```

> Buttons, inputs and links inside `data-axon-drag` are automatically excluded from the drag
> region; add `data-axon-no-drag` to exclude anything else.

## API

### Python

| Name | What it does |
| --- | --- |
| `AxonShellWindow(web_name, url, title=…, size=…, min_size=…, options=…)` | `AxonGUI` subclass: frameless, icon, initial size clamped to the screen, registers `Axon.Window` |
| `Axon.Window` controller | `minimize` `maximize` `restore` `toggleMaximize` `toggleFullScreen` `close` `setAlwaysOnTop` `setTitle` `setDragRegions` `beginSystemMove` `moveTo` `resizeTo` `moveBy` `frame` `state` `platform` `popupMenu` `closeMenu` |
| event `window:state` | maximized / fullscreen / geometry changed (coalesced at 60 ms) |
| event `window:menu` | a native menu item was chosen: `{requestId, id}` |
| `assets_dir()` | the `assets` folder (`shell.js`, icons) |

### Frontend (`window.AxonShell`)

| Name | What it does |
| --- | --- |
| `init(opts?)` | idempotent: wire `data-axon-window`, report `[data-axon-drag]`, subscribe to state/menu events |
| `drag.refresh()` / `drag.regions()` | recompute drag regions after layout changes |
| `window.state()` | `{platform, frame:{x,y,width,height}, maximized, fullScreen}` |
| `window.minimize()` `toggleMaximize()` `close()` `setTitle()` `setAlwaysOnTop()` `refresh()` | common window operations |
| `window.onState(cb)` | subscribe to window state |
| `menu.native(spec)` / `menu.onSelect(cb)` | ask Qt to show a native menu; items support `{id,label,shortcut?,kind?:separator/check/radio,checked?,disabled?,items?}` |
| `enableFallback()` | pointer-drag and 8-way resize on non-Windows platforms (`init()` enables it) |

After `init()`, `<html>` carries `data-axon-platform` and `data-axon-maximized`, so CSS can adapt.

## Per-platform behaviour

- **Windows**: Python answers `WM_NCHITTEST` — reported regions become `HTCAPTION`, 6 px borders become `HTLEFT/HTRIGHT/HTTOP/...`. Dragging, double-click maximize, snapping and resizing are all OS behaviour.
- **Linux / macOS**: `startSystemMove()` first; otherwise `shell.js` falls back to pointer deltas plus eight invisible resize hot zones.

You never write `-webkit-app-region` (Qt does not understand it anyway).

## Example

`examples/basic/` — one draggable bar, three window buttons, three demo buttons.

```bash
cd examples/basic
python main.py                 # needs npm install axon-gui (or point AXON_BUNDLE at axon.umd.cjs)
python main.py --smoke         # headless self-check
python ../../tests/verify.py   # end-to-end: drag regions, buttons, state, resize, Python round-trip, native menu
```

For a full VSCode-style chrome built on top of these primitives, see
[the window-chrome page in the Axon docs](https://axongui.github.io/Axon/en/guide/window-chrome).

## Verify

```bash
python examples/basic/main.py --smoke     # connected + drag regions + window
python tests/verify.py                    # 11 assertions, exit code = failures
```

## Version

`0.2.0` — shrunk from "theme included" to "native layer only". 0.1.x shipped a title bar, menus
and a theme; all of that is gone. You write better chrome than we do.

MIT © STofone
