"""axon-shell 的端到端自检：窗口、菜单、右键菜单、编辑保存、原生菜单。

    python tests/verify.py            # 无头（offscreen），退出码 = 失败条数

它会在临时工作区里起一份示例窗口，逐项操作并打印 PASS/FAIL，最后写 verify_report.json。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "files"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(DEMO))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage"
)

WORKDIR = Path(tempfile.mkdtemp(prefix="axon-shell-verify-"))
os.environ["AXON_FILES_WORKSPACE"] = str(WORKDIR)

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
        self.last_state_event = None
        self.native_picks: list[dict] = []

    # ---- 基础 -----------------------------------------------------------
    def js(self, code: str, callback=None) -> None:
        self.window.page().runJavaScript(code, 0, callback or (lambda _r: None))

    def push(self, expr: str) -> None:
        """执行表达式并把结果塞进页面里的队列（Promise 也会被等到）。"""
        self.js(
            "Promise.resolve(%s).then(v => window.__v.push(v)).catch(e => window.__v.push({error: String(e && e.message || e)}))"
            % expr
        )

    def take(self, then, delay: int = 200, tries: int = 12) -> None:
        """取结果队列；离屏下 Chromium 会节流定时器，所以空队列要重试。"""

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
        self.steps.pop(0)()

    def finish(self) -> None:
        failed = [r for r in RESULTS if not r["ok"]]
        print("\n" + "=" * 64)
        print(f"共 {len(RESULTS)} 条, 失败 {len(failed)} 条")
        report = {
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": RESULTS,
            "workspace": str(WORKDIR),
        }
        (ROOT / "tests" / "verify_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.rmtree(WORKDIR, ignore_errors=True)
        self.app.exit(len(failed))

    # ---- 步骤 -----------------------------------------------------------
    def boot(self) -> None:
        """等页面连上后端，再注入结果队列（注入必须发生在真实文档里，不能是 about:blank）。"""
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
                record("boot/connected", True, f"platform={info.get('platform')} theme={info.get('theme')}")
                record("boot/chrome", bool(info.get("chrome")))
                record("boot/tree", info.get("rows", 0) > 0, f"rows={info.get('rows')}")
                self.js(
                    "window.__v = { q: [], push(v) { this.q.push(v); }, take() { const s = JSON.stringify(this.q); this.q = []; return s; } }; 'ok'",
                    lambda _r: self.next(),
                )

            self.js("JSON.stringify(globalThis.__files || {})", check)

        QTimer.singleShot(400, poll)

    def step_state(self) -> None:
        self.js("window.axon.Axon.Window.state().then(s => window.__v.push(s)).catch(e => window.__v.push({error: String(e)}))")
        self.take(self.after_state_run)

    # 1) 状态
    def after_state_run(self, batch):
        data = batch[-1] if batch else {}
        record(
            "window/state",
            data.get("width", 0) > 0 and bool(data.get("platform")),
            f"{data.get('width')}x{data.get('height')} platform={data.get('platform')}",
        )
        self.next()

    # 2) 拖拽区
    def step_drag(self) -> None:
        self.js("window.axon.Axon.Window.setDragRegions([{x:200,y:0,w:400,h:36}]).then(() => window.__v.push(1))")
        self.take(lambda _batch: (record("window/drag_regions", len(self.window._drag_regions) >= 1, f"{self.window._drag_regions}"), self.next()))

    # 3) 最大化 / 还原
    def step_max(self) -> None:
        self.js(
            "window.axon.Axon.Window.maximize().then(() => new Promise(r => setTimeout(r, 500)))"
            ".then(() => window.axon.Axon.Window.state()).then(s => window.__v.push(s))"
        )
        self.take(self.after_max)

    def after_max(self, batch):
        data = batch[-1] if batch else {}
        record("window/maximize", data.get("maximized") is True, f"maximized={data.get('maximized')}")
        self.next()

    def step_restore(self) -> None:
        self.js(
            "window.axon.Axon.Window.restore().then(() => new Promise(r => setTimeout(r, 450)))"
            ".then(() => window.axon.Axon.Window.state()).then(s => window.__v.push(s))"
        )
        self.take(self.after_restore)

    def after_restore(self, batch):
        data = batch[-1] if batch else {}
        record("window/restore", data.get("maximized") is False, f"maximized={data.get('maximized')}")
        self.next()

    # 4) 缩放
    def step_resize(self) -> None:
        self.js(
            "window.axon.Axon.Window.resizeTo(1180, 760).then(() => new Promise(r => setTimeout(r, 350)))"
            ".then(() => window.axon.Axon.Window.state()).then(s => window.__v.push(s))"
        )
        self.take(self.after_resize)

    def after_resize(self, batch):
        data = batch[-1] if batch else {}
        ok = abs(int(data.get("width", 0)) - 1180) <= 4 and abs(int(data.get("height", 0)) - 760) <= 4
        record("window/resizeTo", ok, f"{data.get('width')}x{data.get('height')}")
        self.next()

    # 5) 网页菜单：视图 → 显示输出面板
    def step_html_menu(self) -> None:
        self.js(
            """(() => {
              const btn = document.querySelector('[data-menu="view"]');
              if (!btn) return 'no-button';
              btn.click();
              return 'ok';
            })()""",
            lambda r: self.take(self.after_menu_open),
        )

    def after_menu_open(self, batch):
        self.js(
            "JSON.stringify([...document.querySelectorAll('.axs-menu__item')].map(i => i.textContent.trim()))",
            lambda raw: (
                record("menu/open", bool(raw) and len(json.loads(raw)) >= 3, (raw or "")[:80]),
                self.click_panel_toggle(),
            ),
        )

    def click_panel_toggle(self):
        def run():
            self.js(
                """(() => {
                  const item = [...document.querySelectorAll('.axs-menu__item')]
                    .find(i => i.textContent.includes('显示输出面板'));
                  if (!item) return 'missing';
                  item.click();
                  return 'ok';
                })()""",
                lambda r: QTimer.singleShot(
                    400,
                    lambda: self.js(
                        "JSON.stringify({hidden: document.documentElement.dataset.panel === 'hidden'})",
                        lambda raw: (
                            record("menu/action", json.loads(raw)["hidden"] is True, raw or ""),
                            self.next(),
                        ),
                    ),
                ),
            )

        QTimer.singleShot(150, run)

    # 6) 右键菜单
    def step_context(self) -> None:
        self.js(
            """(() => {
              const row = [...document.querySelectorAll('.tree__row')].find(r => r.dataset.dir === 'false');
              if (!row) return 'no-row';
              const box = row.getBoundingClientRect();
              row.dispatchEvent(new MouseEvent('contextmenu', {
                bubbles: true, clientX: box.left + 40, clientY: box.top + 8,
              }));
              return 'ok';
            })()"""
        )
        QTimer.singleShot(
            350,
            lambda: self.js(
                "JSON.stringify([...document.querySelectorAll('.axs-menu__item')].map(i => i.textContent.trim()))",
                lambda raw: (
                    record("contextmenu/html", bool(raw) and len(json.loads(raw)) >= 6, (raw or "")[:100]),
                    self.js("AxonShell.closeMenu()", lambda _r: self.next()),
                ),
            ),
        )

    # 7) 打开文件 / 改内容 / Ctrl+S
    def step_editor(self) -> None:
        self.js(
            """(() => {
              const row = [...document.querySelectorAll('.tree__row')].find(r => r.dataset.path === 'config.json');
              if (!row) return 'no-row';
              row.click();
              return 'ok';
            })()"""
        )
        QTimer.singleShot(
            900,
            lambda: self.js(
                "JSON.stringify({editor: !!document.querySelector('#codearea'), tab: !!document.querySelector('.tab')})",
                lambda raw: (
                    record("editor/open", bool(raw) and json.loads(raw).get("editor") is True, raw or ""),
                    self.save_editor(),
                ),
            ),
        )

    def save_editor(self) -> None:
        self.js(
            """(() => {
              const area = document.querySelector('#codearea');
              if (!area) return 'no-editor';
              area.value = '{"touched": true}\\n';
              area.dispatchEvent(new Event('input', {bubbles: true}));
              document.dispatchEvent(new KeyboardEvent('keydown', {key: 's', ctrlKey: true, bubbles: true}));
              return 'ok';
            })()"""
        )
        QTimer.singleShot(
            700,
            lambda: self.check_saved(),
        )

    def check_saved(self) -> None:
        target = WORKDIR / "config.json"
        content = target.read_text(encoding="utf-8") if target.exists() else ""
        record("editor/save", "touched" in content, f"{len(content)}B -> {target.name}")
        self.next()

    # 8) 原生菜单
    def step_native(self) -> None:
        self.js(
            "window.axon.Axon.Window.popupMenu({title: 'verify', items: [{id: 'na', label: 'A'}, {kind: 'separator'}, {id: 'nb', label: 'B'}]})"
            ".then(rid => window.__v.push(rid))"
        )
        self.take(self.after_native_popup)

    def after_native_popup(self, batch):
        request_id = batch[-1] if batch else None
        menu = self.window._last_menu
        record("menu/native:popup", bool(request_id) and menu is not None, f"requestId={request_id}")
        if not menu:
            return self.next()
        actions = [a for a in menu.actions() if a.data()]
        if actions:
            actions[0].trigger()

        def check():
            self.js(
                "JSON.stringify(globalThis.__files && globalThis.__files.lastMenu || null)",
                lambda raw: (
                    record("menu/native:dispatch", bool(raw) and json.loads(raw).get("id") == "na", raw or ""),
                    self.js("window.axon.Axon.Window.closeMenu()", lambda _r: self.next()),
                ),
            )

        QTimer.singleShot(600, check)


def main() -> int:
    shutil.copy(DEMO / "workspace" / "config.json", WORKDIR / "config.json")
    shutil.copy(DEMO / "workspace" / "README.md", WORKDIR / "README.md")
    (WORKDIR / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy(DEMO / "workspace" / "src" / "app.py", WORKDIR / "src" / "app.py")

    server = demo.start_server(demo.find_axon_bundle(), 0)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    app = QApplication(sys.argv[:1])
    AxonMagicGUI()
    window = AxonShellWindow("FilesDemo", url, title="axon-shell verify", size=(1240, 800))
    window.show()

    h = Harness(app, window)
    h.native_picks = []

    h.steps = [
        h.step_state,
        h.step_drag,
        h.step_max,
        h.step_restore,
        h.step_resize,
        h.step_html_menu,
        h.step_context,
        h.step_editor,
        h.step_native,
    ]
    h.boot()
    QTimer.singleShot(120000, lambda: (record("timeout", False, "120s"), h.finish()))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
