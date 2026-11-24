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
        h.step_native,
    ]
    h.boot()
    QTimer.singleShot(120000, lambda: (record("timeout", False, "120s"), h.finish()))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
