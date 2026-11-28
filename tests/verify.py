"""axon-shell 端到端自检：拖拽区、窗口按钮、状态、缩放、Python 往返、原生菜单。

    python tests/verify.py            # 无头（offscreen），退出码 = 失败条数
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "basic"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(DEMO))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage"
)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main as demo  # noqa: E402
from axon import AxonMagicGUI  # noqa: E402
from axon_shell import AxonShellWindow  # noqa: E402

RESULTS: list[dict] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))


def skip(name: str, reason: str) -> None:
    """记一条 SKIP：不计失败，但显式说明为什么没测（避免「没跑」被当成「通过」）。"""
    RESULTS.append({"name": name, "ok": True, "detail": f"SKIP: {reason}", "skipped": True})
    print(f"SKIP  {name}  {reason}")


class Harness:
    def __init__(self, app, window: AxonShellWindow):
        self.app = app
        self.window = window
        self.steps: list = []
        self.deadline = time.time() + 120

    # ---- 基础设施 -------------------------------------------------------
    def js(self, code: str, callback=None) -> None:
        self.window.page().runJavaScript(code, 0, callback or (lambda _r: None))

    def push(self, expr: str) -> None:
        self.js(
            "Promise.resolve(%s).then(v => window.__v.push(v))"
            ".catch(e => window.__v.push({error: String(e && e.message || e)}))" % expr
        )

    def take(self, then, delay: int = 200, tries: int = 15) -> None:
        def once(left):
            def handle(raw):
                batch = json.loads(raw or "[]")
                if not batch and left > 1:
                    QTimer.singleShot(delay, lambda: once(left - 1))
                    return
                then(batch)

            self.js("window.__v.take()", handle)

        QTimer.singleShot(delay, lambda: once(tries))

    def next(self) -> None:
        if time.time() > self.deadline:
            record("timeout", False, "自检超时")
            return self.finish()
        if not self.steps:
            return self.finish()
        step = self.steps.pop(0)
        # 永远不在 runJavaScript 的回调里直接执行下一步：QT→JS 的事件在这种上下文里会卡住
        QTimer.singleShot(30, step)

    def finish(self) -> None:
        failed = [r for r in RESULTS if not r["ok"]]
        print("\n" + "=" * 64)
        print(f"共 {len(RESULTS)} 条, 失败 {len(failed)} 条")
        report = {
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": RESULTS,
        }
        (ROOT / "tests" / "verify_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.app.exit(len(failed))

    # ---- 0) 启动 --------------------------------------------------------
    def boot(self) -> None:
        state = {"n": 0}

        def poll():
            state["n"] += 1
            if state["n"] > 100:
                record("boot/timeout", False, "前端 30s 没连上")
                return self.finish()

            def check(raw):
                info = json.loads(raw) if raw else {}
                if not info.get("connected"):
                    return QTimer.singleShot(300, poll)
                record("boot/connected", True, f"platform={info.get('platform')}")
                record("boot/drag_target", bool(info.get("drag")), "[data-axon-drag] 存在")
                record(
                    "boot/drag_regions",
                    int(info.get("regions") or 0) >= 1,
                    f"regions={info.get('regions')}",
                )
                self.js(
                    "window.__v = { q: [], push(v) { this.q.push(v); }, "
                    "take() { const s = JSON.stringify(this.q); this.q = []; return s; } }; 'ok'",
                    lambda _r: self.next(),
                )

            self.js("JSON.stringify(globalThis.__demo || {})", check)

        QTimer.singleShot(500, poll)

    # ---- 1) 窗口状态 ----------------------------------------------------
    def step_state(self) -> None:
        self.push("window.axon.Axon.Window.state()")
        self.take(self.after_state)

    def after_state(self, batch):
        data = batch[-1] if batch else {}
        record(
            "window/state",
            data.get("width", 0) > 0 and bool(data.get("platform")),
            f"{data.get('width')}x{data.get('height')} platform={data.get('platform')}",
        )
        self.next()

    # ---- 2) 拖拽区真上报到 Qt -------------------------------------------
    def step_drag(self) -> None:
        self.push("(window.AxonShell.drag.refresh(), 1)")
        QTimer.singleShot(
            500,
            lambda: (
                record(
                    "window/drag_regions_reported",
                    len(self.window._drag_regions) >= 1,
                    f"{len(self.window._drag_regions)} 段",
                ),
                self.next(),
            ),
        )

    # ---- 3) 窗口按钮（data-axon-window 自动接线） -----------------------
    def step_max(self) -> None:
        self.js("document.querySelector('[data-axon-window=\"max\"]').click()")
        QTimer.singleShot(
            700,
            lambda: self.push("window.axon.Axon.Window.state()") or self.take(self.after_max),
        )

    def after_max(self, batch):
        data = batch[-1] if batch else {}
        record("window/button_max", data.get("maximized") is True, f"maximized={data.get('maximized')}")
        self.next()

    def step_restore(self) -> None:
        self.js("document.querySelector('[data-axon-window=\"max\"]').click()")
        QTimer.singleShot(
            700,
            lambda: self.push("window.axon.Axon.Window.state()") or self.take(self.after_restore),
        )

    def after_restore(self, batch):
        data = batch[-1] if batch else {}
        record("window/button_restore", data.get("maximized") is False, f"maximized={data.get('maximized')}")
        self.next()

    # ---- 4) 缩放 --------------------------------------------------------
    def step_resize(self) -> None:
        self.push(
            "window.axon.Axon.Window.resizeTo(900, 620)"
            ".then(() => new Promise(r => setTimeout(r, 350)))"
            ".then(() => window.axon.Axon.Window.state())"
        )
        self.take(self.after_resize)

    def after_resize(self, batch):
        data = batch[-1] if batch else {}
        ok = abs(int(data.get("width", 0)) - 900) <= 6 and abs(int(data.get("height", 0)) - 620) <= 6
        record("window/resizeTo", ok, f"{data.get('width')}x{data.get('height')}")
        self.next()

    # ---- 6) 位置：setBounds / center / screens -------------------------
    def step_bounds(self) -> None:
        self.push(
            "window.axon.Axon.Window.setBounds(120, 90, 860, 600)"
            ".then(() => new Promise(r => setTimeout(r, 300)))"
            ".then(() => window.axon.Axon.Window.frame())"
        )
        self.take(lambda batch: self._after_frame("window/setBounds", batch, 120, 90, 860, 600))

    def _after_frame(self, name, batch, x, y, w, h) -> None:
        data = batch[-1] if batch else {}
        ok = (
            abs(int(data.get("x", -999)) - x) <= 8
            and abs(int(data.get("y", -999)) - y) <= 8
            and abs(int(data.get("width", 0)) - w) <= 8
            and abs(int(data.get("height", 0)) - h) <= 8
        )
        record(name, ok, f"{data.get('width')}x{data.get('height')} @ ({data.get('x')},{data.get('y')})")
        if name == "window/center":
            self.next()
        else:
            self.next()

    def step_center(self) -> None:
        self.push(
            "window.axon.Axon.Window.center()"
            ".then(() => new Promise(r => setTimeout(r, 300)))"
            ".then(() => window.axon.Axon.Window.frame())"
        )
        self.take(self._after_center)

    def _after_center(self, batch) -> None:
        data = batch[-1] if batch else {}
        screens = getattr(self, "_screens", None) or []
        screen = screens[0] if screens else {}
        w, h = int(data.get("width", 0)), int(data.get("height", 0))
        cx = int(screen.get("workX", 0)) + (int(screen.get("workWidth", 0)) - w) // 2
        cy = int(screen.get("workY", 0)) + (int(screen.get("workHeight", 0)) - h) // 2
        ok = abs(int(data.get("x", -9999)) - cx) <= 12 and abs(int(data.get("y", -9999)) - cy) <= 12
        record("window/center", ok, f"({data.get('x')},{data.get('y')}) 期望 ({cx},{cy})")
        self.next()

    def step_screens(self) -> None:
        self.push("window.axon.Axon.Window.screens()")
        self.take(self._after_screens)

    def _after_screens(self, batch) -> None:
        data = batch[-1] if batch else []
        ok = isinstance(data, list) and len(data) >= 1 and "workWidth" in (data[0] or {})
        if ok:
            self._screens = data
        record("window/screens", ok, f"{len(data) if isinstance(data, list) else 0} 块屏")
        self.next()

    # ---- 7) 尺寸约束与可缩放 -------------------------------------------
    def step_resizable_off(self) -> None:
        self.push(
            "window.axon.Axon.Window.setResizable(false)"
            ".then(() => new Promise(r => setTimeout(r, 200)))"
            ".then(() => window.axon.Axon.Window.state())"
        )
        QTimer.singleShot(
            700,
            lambda: (
                record(
                    "window/resizable_off",
                    self.window.minimumSize() == self.window.maximumSize(),
                    f"min={self.window.minimumSize().toTuple()} max={self.window.maximumSize().toTuple()}",
                ),
                self.next(),
            ),
        )

    def step_min_size(self) -> None:
        self.push(
            "window.axon.Axon.Window.setMinimumSize(700, 500)"
            ".then(() => window.axon.Axon.Window.resizeTo(420, 320))"
            ".then(() => new Promise(r => setTimeout(r, 300)))"
            ".then(() => window.axon.Axon.Window.state())"
        )
        self.take(self._after_min_size)

    def _after_min_size(self, batch) -> None:
        data = batch[-1] if batch else {}
        w, h = int(data.get("width", 0)), int(data.get("height", 0))
        record("window/minSize", w >= 700 and h >= 500, f"{w}x{h}（最小 700x500）")
        self.next()

    def step_resizable_on(self) -> None:
        self.push(
            "window.axon.Axon.Window.setResizable(true)"
            ".then(() => window.axon.Axon.Window.setMaximumSize(0, 0))"
            ".then(() => window.axon.Axon.Window.resizeTo(880, 620))"
            ".then(() => new Promise(r => setTimeout(r, 300)))"
            ".then(() => window.axon.Axon.Window.state())"
        )
        self.take(self._after_resizable_on)

    def _after_resizable_on(self, batch) -> None:
        data = batch[-1] if batch else {}
        w = int(data.get("width", 0))
        record("window/resizable_on", abs(w - 880) <= 8, f"{w}（期望 880）")
        self.next()

    # ---- 8) 透明度 / 显隐 / 关闭守卫 ------------------------------------
    def step_opacity(self) -> None:
        self.push("window.axon.Axon.Window.setOpacity(0.85).then(() => 1)")
        QTimer.singleShot(
            500,
            lambda: (
                record(
                    "window/opacity",
                    abs(self.window.windowOpacity() - 0.85) < 0.05,
                    f"{self.window.windowOpacity():.2f}",
                ),
                self.next(),
            ),
        )

    def step_visible(self) -> None:
        def check() -> None:
            record("window/hide_show", self.window.isVisible(), f"isVisible={self.window.isVisible()}")
            self.next()

        self.push("window.axon.Axon.Window.hide()")
        QTimer.singleShot(
            400,
            lambda: (
                record("window/hide", not self.window.isVisible(), f"isVisible={self.window.isVisible()}"),
                self.push("window.axon.Axon.Window.show()"),
                QTimer.singleShot(500, check),
            ),
        )

    def step_close_guard(self) -> None:
        js = (
            "(window.__guardHit = 0, "
            "window.__disposeGuard = window.AxonShell.window.onCloseRequest(() => { window.__guardHit++; }), 1)"
        )
        self.push(js)
        QTimer.singleShot(500, self._guard_close)

    def _guard_close(self) -> None:
        self.push("window.axon.Axon.Window.close()")
        QTimer.singleShot(
            600,
            lambda: (
                record("window/close_guard", self.window.isVisible(), "有守卫时窗口没被关掉"),
                self.window.__setattr__("_close_guard", False),
                self.window.__setattr__("_allow_close", False),
                self.next(),
            ),
        )

    # ---- 5) JS → Python 往返 --------------------------------------------
    def step_echo(self) -> None:
        self.push("window.axon.Axon.App.echo('hello')")
        self.take(self.after_echo)

    def after_echo(self, batch):
        value = batch[-1] if batch else None
        record("py/echo", value == "Python 收到：hello", str(value))
        self.next()

    # ---- 6) 原生菜单选中项回传（不弹菜单，避免 offscreen 的 QMenu 卡住事件循环） ----
    def step_menu_dispatch(self) -> None:
        # 不能在 runJavaScript 的回调里直接发 QT→JS 的事件（会卡住渲染进程），
        # 先排到下一轮事件循环。
        QTimer.singleShot(50, lambda: self.window._emit_menu_selected("menu-1", "na"))

        def check(left=15):
            def handle(raw):
                data = json.loads(raw or "null")
                if (not data) and left > 1:
                    QTimer.singleShot(300, lambda: check(left - 1))
                    return
                record("menu/dispatch", data == "na", raw or "")
                self.next()

            self.js(
                "JSON.stringify(globalThis.__demo && globalThis.__demo.lastMenu || null)",
                handle,
            )

        QTimer.singleShot(200, check)

    # ---- 7) 原生菜单：能建出 Qt 菜单（最后一步，之后不再依赖 JS 回调） ----
    def step_native(self) -> None:
        # 原生菜单（GetSystemMenu / TrackPopupMenu）只有 Windows 实现；
        # 在 macOS/Linux 上这条本来就不该是绿的，所以显式跳过而不是让它 FAIL。
        if os.environ.get("AXON_SKIP_NATIVE_MENU") == "1" or sys.platform != "win32":
            skip("menu/native:popup", "原生菜单只有 Windows 实现")
            return self.finish()
        self.push(
            "window.AxonShell.menu.native({id: 'verify', items: "
            "[{id: 'na', label: 'A'}, {kind: 'separator'}, {id: 'nb', label: 'B'}]})"
        )
        self.take(self.after_native_popup)

    def after_native_popup(self, batch):
        request_id = batch[-1] if batch else None
        menu = self.window._last_menu
        ids = [a.data() for a in menu.actions() if a.data()] if menu else []
        record(
            "menu/native:popup",
            bool(request_id) and menu is not None and ids == ["na", "nb"],
            f"requestId={request_id} items={ids}",
        )
        # offscreen 平台上 QMenu 一弹出就会占住事件循环（真窗口正常），
        # 所以这里直接收尾：这是最后一步，不再依赖定时器或 JS 回调。
        if menu:
            menu.close()
            self.window._last_menu = None
        self.finish()


def main() -> int:
    server = demo.start_server(demo.find_axon_bundle(), 0)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    app = QApplication(sys.argv[:1])
    AxonMagicGUI()
    window = AxonShellWindow("BasicDemo", url, title="axon-shell verify", size=(980, 680))
    window.show()

    h = Harness(app, window)
    h.steps = [
        h.step_menu_dispatch,
        h.step_state,
        h.step_drag,
        h.step_max,
        h.step_restore,
        h.step_resize,
        h.step_echo,
        h.step_bounds,
        h.step_screens,
        h.step_center,
        h.step_resizable_off,
        h.step_min_size,
        h.step_resizable_on,
        h.step_opacity,
        h.step_visible,
        h.step_close_guard,
        h.step_native,
    ]
    h.boot()
    QTimer.singleShot(120000, lambda: (record("timeout", False, "120s"), h.finish()))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
