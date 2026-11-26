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
from PySide6.QtGui import QAction, QActionGroup, QCursor, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import QMenu, QApplication

from axon import AxonController, AxonEvent, AxonGUI, AxonMagicGUI



WebName = str

__all__ = ["AxonShellWindow", "AxonWindow", "WindowBridge", "assets_dir"]


def assets_dir() -> str:
    """前端资源目录（`shell.js` 与图标），用静态服务挂出去即可。"""
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
        self._close_guard = False  # 页面注册了「关闭前问问」才拦
        self._allow_close = False
        self._resizable = True
        self._skip_taskbar = False
        self._close_guard = False  # 页面注册了「关闭前问问」才拦
        self._allow_close = False
        self._resizable = True
        self._skip_taskbar = False

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle(title)
        self._min_size = (int(min_size[0]), int(min_size[1]))
        self.setMinimumSize(*min_size)
        self._fit_to_screen(size)
        self._apply_icon(QApplication.instance())

        self.window_bridge = WindowBridge(self)
        AxonController.register(self.window_bridge, web_name=web_name, id="Window")
        self.loadFinished.connect(lambda _ok: self._emit_state())

    def _fit_to_screen(self, desired: tuple[int, int]) -> None:
        """窗口别大过屏幕：按可用区域收 94%，然后居中。"""
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        width, height = desired
        if available is not None:
            width = min(width, int(available.width() * 0.94))
            height = min(height, int(available.height() * 0.94))
        self.resize(width, height)
        if available is not None:
            self.move(
                available.x() + (available.width() - width) // 2,
                available.y() + (available.height() - height) // 2,
            )

    @staticmethod
    def _apply_icon(app: Optional[QApplication]) -> None:
        """没图标就补一个（宿主已经设过就不覆盖）。"""
        icon_file = Path(assets_dir()) / "icon-256.png"
        if app is None or not icon_file.is_file() or not app.windowIcon().isNull():
            return
        app.setWindowIcon(QIcon(str(icon_file)))

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
            "visible": self.isVisible(),
            "focused": self.isActiveWindow(),
            "alwaysOnTop": bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
            "resizable": self._resizable,
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

    # ------------------------------------------------------------------ 尺寸与外观
    def set_min_size(self, width: int, height: int):
        self.setMinimumSize(max(0, int(width)), max(0, int(height)))

    def set_max_size(self, width: int, height: int):
        """0 / 0 表示不限制。"""
        self.setMaximumSize(int(width) or 16777215, int(height) or 16777215)

    def set_resizable(self, on: bool):
        self._resizable = bool(on)
        if self._resizable:
            self.setMinimumSize(self._min_size[0], self._min_size[1])
            self.setMaximumSize(16777215, 16777215)
        else:
            size = self.size()
            self.setFixedSize(size)
        self._schedule_state()

    def apply_skip_taskbar(self, skip: bool):
        """不占任务栏 / Alt-Tab（`Tool` 窗口）。"""
        self._skip_taskbar = bool(skip)
        flags = self.windowFlags()
        if self._skip_taskbar:
            flags |= Qt.WindowType.Tool
        else:
            flags &= ~Qt.WindowType.Tool
        visible = self.isVisible()
        self.setWindowFlags(flags)
        if visible:
            self.show()

    def flash(self, msec: int = 0) -> bool:
        """请求注意力（Windows 任务栏闪烁 / macOS 跳 Dock）。"""
        QApplication.alert(self, max(0, int(msec)))
        return True

    def set_opacity_value(self, value: float):
        self.setWindowOpacity(min(1.0, max(0.1, float(value))))

    def center_on_current_screen(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        geo = self.frameGeometry()
        self.move(
            area.x() + (area.width() - geo.width()) // 2,
            area.y() + (area.height() - geo.height()) // 2,
        )

    def set_bounds(self, x: int, y: int, width: int, height: int):
        self.setGeometry(int(x), int(y), max(1, int(width)), max(1, int(height)))

    # ------------------------------------------------------------------ 屏幕
    def screens_info(self) -> list[dict[str, Any]]:
        primary = QGuiApplication.primaryScreen()
        result: list[dict[str, Any]] = []
        for screen in QGuiApplication.screens():
            geo, area = screen.geometry(), screen.availableGeometry()
            result.append(
                {
                    "name": screen.name(),
                    "x": geo.x(),
                    "y": geo.y(),
                    "width": geo.width(),
                    "height": geo.height(),
                    "workX": area.x(),
                    "workY": area.y(),
                    "workWidth": area.width(),
                    "workHeight": area.height(),
                    "scale": float(screen.devicePixelRatio()),
                    "primary": screen is primary,
                }
            )
        return result

    def current_screen_info(self) -> dict[str, Any]:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return {}
        geo = screen.geometry()
        for info in self.screens_info():
            if info["name"] == screen.name() and info["width"] == geo.width():
                return info
        return {"name": screen.name(), "width": geo.width(), "height": geo.height()}

    # ------------------------------------------------------------------ Windows 系统菜单
    def system_menu(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """在指定位置弹原生窗口菜单（还原/移动/大小/最小化/最大化/关闭）。"""
        if PLATFORM != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.GetSystemMenu.restype = wintypes.HMENU
            user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
            user32.TrackPopupMenu.restype = ctypes.c_int
            user32.TrackPopupMenu.argtypes = [
                wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, wintypes.HWND, ctypes.c_void_p,
            ]
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

            hwnd = wintypes.HWND(int(self.winId()))
            menu = user32.GetSystemMenu(hwnd, False)
            if not menu:
                return False
            maximized = self.isMaximized()
            # 按当前状态把「还原/最大化」置灰
            user32.EnableMenuItem(menu, 0xF120, 0 if maximized else 0x1)   # SC_RESTORE
            user32.EnableMenuItem(menu, 0xF030, 0x1 if maximized else 0)   # SC_MAXIMIZE
            origin = self.mapToGlobal(QPoint(0, 0))
            px = origin.x() + (int(x) if isinstance(x, (int, float)) else 40)
            py = origin.y() + (int(y) if isinstance(y, (int, float)) else 40)
            cmd = user32.TrackPopupMenu(menu, 0x0100 | 0x0002 | 0x0004 | 0x0008, px, py, 0, hwnd, None)
            if cmd:
                user32.PostMessageW(hwnd, 0x0112, cmd, 0)
            return True
        except Exception:
            return False

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

    def moveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().moveEvent(event)
        self._schedule_state()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._schedule_state()

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().focusInEvent(event)
        self._schedule_state()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().focusOutEvent(event)
        self._schedule_state()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """页面注册了关闭守卫时，先问一句再关（比如「有未保存修改」）。

        JS 侧 `AxonShell.window.onCloseRequest(fn)` 注册处理函数后，会调
        `Window.setCloseGuard(true)`；处理函数里可以异步决定，最后调
        `AxonShell.window.confirmClose()` 才会真的关。
        """
        if self._close_guard and not self._allow_close:
            self._allow_close = False
            try:
                AxonEvent.dispatch_js_event(self.web_name, "window:closerequest", [])
            except Exception:
                pass
            event.ignore()
            return
        super().closeEvent(event)

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
                        # WM_NCHITTEST 的坐标是物理像素；Qt 的 mapFromGlobal 要逻辑像素
                        dpr = self.devicePixelRatioF() or 1.0
                        logical = QPoint(int(x / dpr), int(y / dpr))
                        hit = self._hit_test(self.mapFromGlobal(logical))
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

    # ---------------------------------------------------------------- 显隐与焦点
    @Slot()
    def show(self):
        self._gui(self._window.show)

    @Slot()
    def hide(self):
        self._gui(self._window.hide)

    @Slot()
    def showWindow(self):  # noqa: N802 - 兼容旧写法
        self.show()

    @Slot()
    def hideWindow(self):  # noqa: N802 - 兼容旧写法
        self.hide()

    @Slot()
    def activate(self):
        def apply():
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

        self._gui(apply)

    @Slot(result=bool)
    def isVisible(self) -> bool:  # noqa: N802
        return bool(self._gui(self._window.isVisible))

    @Slot(int, int)
    def setMinimumSize(self, width: int, height: int):  # noqa: N802
        self._gui(lambda: self._window.set_min_size(width, height))

    @Slot(int, int)
    def setMaximumSize(self, width: int, height: int):  # noqa: N802
        self._gui(lambda: self._window.set_max_size(width, height))

    @Slot(bool)
    def setResizable(self, on: bool):  # noqa: N802
        self._gui(lambda: self._window.set_resizable(_as_bool(on)))

    @Slot(float)
    def setOpacity(self, value: float):  # noqa: N802
        self._gui(lambda: self._window.set_opacity_value(float(value)))

    @Slot(bool)
    def setSkipTaskbar(self, skip: bool):  # noqa: N802
        self._gui(lambda: self._window.apply_skip_taskbar(_as_bool(skip)))

    @Slot(result=bool)
    def flash(self) -> bool:
        return bool(self._gui(self._window.flash))

    @Slot(bool)
    def setCloseGuard(self, on: bool):  # noqa: N802
        """页面注册了「关闭前问问」时打开；关闭要再调 close() 才生效。"""

        def apply():
            self._window._close_guard = _as_bool(on)
            if not self._window._close_guard:
                self._window._allow_close = False

        self._gui(apply)

    @Slot(result=bool)
    def confirmClose(self) -> bool:  # noqa: N802
        def apply():
            self._window._allow_close = True
            self._window.close()
            return True

        return bool(self._gui(apply))

    # ---------------------------------------------------------------- 屏幕与位置
    @Slot(result="QVariantList")
    def screens(self) -> list[dict[str, Any]]:
        return self._gui(self._window.screens_info)

    @Slot(result="QVariantMap")
    def currentScreen(self) -> dict[str, Any]:  # noqa: N802
        return self._gui(self._window.current_screen_info)

    @Slot()
    def center(self):
        self._gui(self._window.center_on_current_screen)

    @Slot(int, int, int, int)
    def setBounds(self, x: int, y: int, width: int, height: int):  # noqa: N802
        self._gui(lambda: self._window.set_bounds(x, y, width, height))

    @Slot(int, int, result=bool)
    def systemMenu(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:  # noqa: N802
        """原生窗口菜单（Windows）；其它平台返回 False，由页面自己画。"""
        return bool(self._gui(lambda: self._window.system_menu(x, y)))

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
    def popupMenu(self, spec, x=None, y=None):  # noqa: N802
        """弹出原生菜单，不阻塞；选中项通过 `window:menu` 事件回来。

        x / y 是相对窗口左上角的坐标，省略时用鼠标位置。
        """
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
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                anchor = self._window.mapToGlobal(QPoint(int(x), int(y)))
            else:
                anchor = QCursor.pos()
            menu.popup(anchor)

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
