"""无边框窗口 + 自定义标题栏骨架。

`AxonShellWindow` 就是 `AxonGUI` 加了一层「窗口外观由网页决定」的能力：

* 没有系统标题栏、边框、按钮，全部由网页绘制（VSCode / Electron 那种观感）；
* 网页通过 `Axon.Window` 控制器调用最小化 / 最大化 / 恢复 / 关闭 / 置顶 / 全屏；
* 顶部拖拽区由网页用 `[data-axon-drag]` 标记后上报，Windows 上走原生 `WM_NCHITTEST`
  （于是拖动、双击最大化、拖到屏幕边缘贴靠、四边缩放全是系统行为，没有手搓抖动）；
* 其它平台回退到网页驱动：`beginSystemMove()` 失败时用 `moveTo/resizeTo` 按屏幕坐标增量移动；
* 右键菜单由 Python 侧 `QMenu` 弹出（可选），选中项以 `window:menu` 事件回传，
  网页也可以完全用 HTML 自己画菜单——两条路都在示例里。

窗口状态变化会以 `window:state` 事件广播给前端：`{maximized, fullScreen, width, height, x, y, platform}`。
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, TypedDict

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence
from PySide6.QtWidgets import QMenu


from axon import AxonController, AxonEvent, AxonGUI, AxonMagicGUI



WebName = str

__all__ = ["AxonShellWindow", "AxonWindow", "WindowBridge", "assets_dir"]


def assets_dir() -> str:
    """前端皮肤（shell.css / shell.js）所在目录，用静态服务挂出去即可。"""
    return str(Path(__file__).resolve().parent / "assets")

# Win32 WM_NCHITTEST 的返回值
HTTRANSPARENT = -1
HTNOWHERE = 0
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
WM_NCHITTEST = 0x0084


class DragRect(TypedDict):
    """网页上报的拖拽区（CSS 像素，窗口坐标系）。"""

    x: float
    y: float
    w: float
    h: float


class MenuItem(TypedDict, total=False):
    id: str
    label: str
    kind: str  # normal | separator | check | radio | submenu
    checked: bool
    disabled: bool
    shortcut: str
    submenu: list["MenuItem"]


class MenuSpec(TypedDict, total=False):
    title: str
    items: list[MenuItem]


PLATFORM = (
    "win32" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else "linux"
)


class AxonShellWindow(AxonGUI):
    """无边框窗口：外观与交互交给网页。"""

    def __init__(
        self,
        web_name: WebName,
        url: str,
        options: Optional[dict[str, Any]] = None,
        *,
        title: str = "Axon",
        min_size: tuple[int, int] = (760, 520),
        size: tuple[int, int] = (1280, 840),
        resize_border: int = 6,
        drag_regions: Iterable[DragRect] = (),
    ):
        opts: dict[str, Any] = dict(options or {})
        # 无边框窗口一律自己画右键菜单, 否则 QWebEngineView 会弹原生菜单把自定义 UI 盖掉
        opts.setdefault("disable_native_context_menu", True)
        super().__init__(web_name, url, opts)

        if AxonMagicGUI.instance is None:
            # 窗口控制必须回到 Qt 主线程执行, 这里兜底建一个
            AxonMagicGUI()

        self._resize_border = int(resize_border)
        self._drag_regions: list[DragRect] = [dict(r) for r in drag_regions]
        self._menu_seq = 0
        self._active_menu: Optional[QMenu] = None
        self._last_menu: Optional[QMenu] = None  # 测试钩子
        self._state_dirty = False

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle(title)
        self.setMinimumSize(*min_size)
        self.resize(*size)

        self.window_bridge = WindowBridge(self)
        AxonController.register(self.window_bridge, web_name=web_name, id="Window")
        self.loadFinished.connect(lambda _ok: self._emit_state())

    # ------------------------------------------------------------------ 平台/状态
    @property
    def platform(self) -> str:
        return PLATFORM

    def window_state(self) -> dict[str, Any]:
        return {
            "maximized": self.isMaximized(),
            "fullScreen": self.isFullScreen(),
            "width": self.width(),
            "height": self.height(),
            "x": self.x(),
            "y": self.y(),
            "platform": PLATFORM,
        }

    def set_drag_regions(self, regions: Sequence[DragRect]):
        self._drag_regions = [
            {
                "x": float(r.get("x", 0)),
                "y": float(r.get("y", 0)),
                "w": float(r.get("w", 0)),
                "h": float(r.get("h", 0)),
            }
            for r in regions or ()
        ]

    # ------------------------------------------------------------------ 事件回传
    def _emit_state(self):
        try:
            AxonEvent.dispatch_js_event(
                self.web_name, "window:state", [self.window_state()]
            )
        except Exception:
            # 前端还没握手完时不必吵: 页面加载完成后会主动取一次 state()
            pass

    def _schedule_state(self):
        if self._state_dirty:
            return
        self._state_dirty = True

        def flush():
            self._state_dirty = False
            self._emit_state()

        QTimer.singleShot(60, flush)

    def changeEvent(self, event: QEvent, /) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            self._schedule_state()
        super().changeEvent(event)

    def _emit_menu_selected(self, request_id: str, item_id: Optional[str]):
        try:
            AxonEvent.dispatch_js_event(
                self.web_name,
                "window:menu",
                [{"requestId": request_id, "id": item_id}],
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ Windows 原生命中测试
    def _hit_test(self, pos: QPoint) -> Optional[int]:
        """返回 WM_NCHITTEST 结果；None 表示交回 Qt 默认处理。"""
        if not self.rect().contains(pos):
            return None
        border = self._resize_border
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        if border and not self.isMaximized() and not self.isFullScreen():
            on_left, on_right = x < border, x >= w - border
            on_top, on_bottom = y < border, y >= h - border
            if on_top and on_left:
                return HTTOPLEFT
            if on_top and on_right:
                return HTTOPRIGHT
            if on_bottom and on_left:
                return HTBOTTOMLEFT
            if on_bottom and on_right:
                return HTBOTTOMRIGHT
            if on_left:
                return HTLEFT
            if on_right:
                return HTRIGHT
            if on_top:
                return HTTOP
            if on_bottom:
                return HTBOTTOM
        for region in self._drag_regions:
            if (
                region["x"] <= x <= region["x"] + region["w"]
                and region["y"] <= y <= region["y"] + region["h"]
            ):
                return HTCAPTION
        return None

    def nativeEvent(self, eventType, message):  # noqa: N802 (Qt 命名)
        if PLATFORM == "win32":
            try:
                if bytes(eventType) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                    from ctypes import wintypes

                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == WM_NCHITTEST:
                        x = ctypes.c_short(msg.lParam & 0xFFFF).value
                        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                        hit = self._hit_test(self.mapFromGlobal(QPoint(x, y)))
                        if hit is not None:
                            return True, hit
            except Exception:
                # 任何异常都不能影响窗口正常事件分发
                pass
        return super().nativeEvent(eventType, message)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class _MenuBuilder:
    """把前端传来的菜单描述翻译成 QMenu，并把选中项回传给前端。"""

    def __init__(self, window: AxonShellWindow, request_id: str):
        self.window = window
        self.request_id = request_id

    def build(self, spec: MenuSpec) -> QMenu:
        menu = QMenu(self.window)
        title = spec.get("title")
        if title:
            menu.setTitle(str(title))
        self._fill(menu, spec.get("items") or [])
        return menu

    def _fill(self, menu: QMenu, items: Sequence[MenuItem]):
        group: Optional[QActionGroup] = None
        for item in items:
            kind = str(item.get("kind") or "normal")
            if kind == "separator":
                menu.addSeparator()
                continue
            action = QAction(str(item.get("label") or ""), menu)
            action.setData(item.get("id"))
            if item.get("shortcut"):
                action.setShortcut(QKeySequence(str(item["shortcut"])))
            if item.get("disabled"):
                action.setEnabled(False)
            if kind == "check":
                action.setCheckable(True)
                action.setChecked(_as_bool(item.get("checked")))
            elif kind == "radio":
                if group is None:
                    group = QActionGroup(menu)
                    group.setExclusive(True)
                action.setCheckable(True)
                action.setActionGroup(group)
                action.setChecked(_as_bool(item.get("checked")))
            if item.get("submenu"):
                action.setMenu(self.build({"items": item["submenu"] or []}))
            # 每个 action 自己上报：不依赖 QMenu.triggered
            # （菜单在离屏/被提前关闭时 QMenu 可能已失效，action 仍应可用）
            action.triggered.connect(
                lambda _checked=False, act=action: self._on_triggered(act)
            )
            menu.addAction(action)

    def _on_triggered(self, action: QAction):
        item_id = action.data()
        menu = action.parent()
        while isinstance(menu, QMenu):
            menu.close()
            menu = menu.parent()
        self.window._active_menu = None
        self.window._emit_menu_selected(
            self.request_id, None if item_id is None else str(item_id)
        )


class WindowBridge(QObject):
    """暴露给网页的 `Axon.Window`。

    这些方法都是同步调用, 但它们必须跑在 Qt 主线程: 控制器默认在线程池里执行,
    所以统一用 `AxonMagicGUI.run(...)` 回主线程, 再等结果。
    """

    def __init__(self, window: AxonShellWindow):
        super().__init__()
        self._window = window

    def _gui(self, func, timeout: float = 5.0):
        return AxonMagicGUI.run(func).result(timeout)

    # ---------------------------------------------------------------- 只读信息
    @Slot(result="QVariantMap")
    def state(self) -> dict[str, Any]:
        return self._gui(self._window.window_state)

    @Slot(result="QString")
    def platform(self) -> str:
        return PLATFORM

    @Slot(result=bool)
    def isMaximized(self) -> bool:  # noqa: N802
        return self._gui(self._window.isMaximized)

    @Slot(result="QVariantMap")
    def frame(self) -> dict[str, Any]:
        def read():
            geo = self._window.frameGeometry()
            return {
                "x": geo.x(),
                "y": geo.y(),
                "width": geo.width(),
                "height": geo.height(),
            }

        return self._gui(read)

    # ---------------------------------------------------------------- 窗口按钮
    @Slot()
    def minimize(self):
        self._gui(self._window.showMinimized)

    @Slot()
    def maximize(self):
        self._gui(self._window.showMaximized)

    @Slot()
    def restore(self):
        self._gui(self._window.showNormal)

    @Slot(result=bool)
    def toggleMaximize(self) -> bool:  # noqa: N802
        def toggle():
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()
            return self._window.isMaximized()

        return bool(self._gui(toggle))

    @Slot()
    def toggleFullScreen(self):  # noqa: N802
        def toggle():
            if self._window.isFullScreen():
                self._window.showNormal()
            else:
                self._window.showFullScreen()

        self._gui(toggle)

    @Slot()
    def close(self):
        self._gui(self._window.close)

    @Slot(bool)
    def setAlwaysOnTop(self, on: bool):  # noqa: N802
        value = _as_bool(on)

        def apply():
            flags = self._window.windowFlags()
            if value:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            visible = self._window.isVisible()
            self._window.setWindowFlags(flags)
            if visible:
                self._window.show()

        self._gui(apply)

    @Slot(str)
    def setTitle(self, title: str):  # noqa: N802
        self._gui(lambda: self._window.setWindowTitle(str(title)))

    # ---------------------------------------------------------------- 拖动/缩放
    @Slot("QVariantList")
    def setDragRegions(self, *regions):  # noqa: N802
        """网页上报可拖拽区域。

        两种写法都收：`setDragRegions([{...}, {...}])`（一个数组参数）与
        `setDragRegions({...}, {...})`（摊开）。前者在旧版 axon-gui 上会被
        当成打包写法展开，所以这里两种形状都要能接。
        """
        if len(regions) == 1 and isinstance(regions[0], (list, tuple)):
            regions = tuple(regions[0])
        data = [dict(r) for r in regions if isinstance(r, dict)]
        self._gui(lambda: self._window.set_drag_regions(data))

    @Slot(result=bool)
    def beginSystemMove(self) -> bool:  # noqa: N802
        """交给系统拖窗（X11/macOS 可用）；Windows 走原生命中测试，不需要它。"""

        def begin():
            handle = self._window.windowHandle()
            if handle is None:
                return False
            return bool(handle.startSystemMove())

        try:
            return bool(self._gui(begin))
        except Exception:
            return False

    @Slot(int, int)
    def moveTo(self, x: int, y: int):
        self._gui(lambda: self._window.move(int(x), int(y)))

    @Slot(int, int)
    def resizeTo(self, width: int, height: int):  # noqa: N802
        def apply():
            w = max(int(width), self._window.minimumWidth())
            h = max(int(height), self._window.minimumHeight())
            self._window.resize(w, h)

        self._gui(apply)

    @Slot(int, int)
    def moveBy(self, dx: int, dy: int):
        def apply():
            self._window.move(self._window.x() + int(dx), self._window.y() + int(dy))

        self._gui(apply)

    # ---------------------------------------------------------------- 菜单
    @Slot("QVariantMap", result="QString")
    def popupMenu(self, spec):  # noqa: N802
        """弹出原生菜单，不阻塞；选中项通过 `window:menu` 事件回来。"""
        payload: MenuSpec = dict(spec or {})
        self._window._menu_seq += 1
        request_id = f"menu-{self._window._menu_seq}"

        def show():
            if self._window._active_menu is not None:
                self._window._active_menu.close()
                self._window._active_menu = None
            builder = _MenuBuilder(self._window, request_id)
            menu = builder.build(payload)
            menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            self._window._active_menu = menu
            self._window._last_menu = menu
            if payload.get("title"):
                menu.setTitle(str(payload["title"]))
            menu.popup(QCursor.pos())

        AxonMagicGUI.run(show)
        return request_id

    @Slot()
    def closeMenu(self):  # noqa: N802
        def hide():
            if self._window._active_menu is not None:
                self._window._active_menu.close()
                self._window._active_menu = None

        self._gui(hide)


# 旧名字，方便迁移
AxonWindow = AxonShellWindow
