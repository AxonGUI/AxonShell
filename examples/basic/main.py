"""最小示例：一个无边框窗口，一条可拖动的顶栏，三个窗口按钮。

它只演示 `axon-shell` 提供的原语；窗口长什么样、放什么按钮、要不要菜单，
都是你自己在 web/ 里写的。

    python main.py                 # 打开窗口
    python main.py --smoke         # 无头自检（不需要显示器）
"""

from __future__ import annotations

import argparse
import os
import threading
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(getattr(sys, "frozen", Path(__file__).resolve().parent))
WEB_DIR = BASE_DIR / "web"
BRAND_FILE = (BASE_DIR / "axon-mark.svg") if getattr(sys, "frozen", False) else BASE_DIR.parent.parent / "assets" / "axon-mark.svg"

WEB_NAME = "BasicDemo"

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from axon import AxonController, AxonMagicGUI  # noqa: E402
from axon_shell import AxonShellWindow, assets_dir  # noqa: E402

SHELL_ASSETS = Path(assets_dir())


def find_axon_bundle() -> Path:
    """优先用 AXON_BUNDLE，再找 node_modules / 本仓库 / 隔壁仓库构建出来的那份。"""
    override = os.environ.get("AXON_BUNDLE")
    if override and Path(override).exists():
        return Path(override)
    for candidate in (
        BASE_DIR / "vendor" / "axon.umd.cjs",
        BASE_DIR / "vendor-axon" / "axon.umd.cjs",
        BASE_DIR / "node_modules" / "axon-gui" / "dist" / "axon.umd.cjs",
        BASE_DIR.parent.parent / "core-js" / "dist" / "axon.umd.cjs",
        BASE_DIR.parent.parent.parent / "Axon" / "core-js" / "dist" / "axon.umd.cjs",
    ):
        if candidate.exists():
            return candidate
    raise SystemExit(
        "找不到 axon 的前端产物：先在 examples/basic 里 npm install axon-gui，"
        "或在仓库里 (cd core-js && npm run build)"
    )


@AxonController(WEB_NAME, id="App")
class BasicController:
    """页面能调的两个方法——真正的业务当然不是这么点。"""

    def echo(self, text: str = "") -> str:
        return f"Python 收到：{text}"

    def about(self) -> dict:
        from PySide6 import __version__ as qt_version

        return {
            "python": sys.version.split()[0],
            "qt": qt_version,
            "platform": sys.platform,
            "shell": "axon-shell",
        }

    def open_url(self, url: str) -> dict:
        QDesktopServices.openUrl(QUrl(url))
        return {"opened": url}


class Handler(SimpleHTTPRequestHandler):
    bundle: Path | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _send(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        # 开发时别让 Chromium 缓存静态资源（改了 shell.js 立刻生效）
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/vendor/axon.umd.cjs", "/vendor/axon.js"):
            return self._send(self.bundle, "text/javascript; charset=utf-8")
        if path == "/brand.svg":
            return self._send(BRAND_FILE, "image/svg+xml")
        if path == "/axon-shell/shell.js":
            return self._send(SHELL_ASSETS / "shell.js", "text/javascript; charset=utf-8")
        return super().do_GET()

    def log_message(self, fmt, *args):
        pass


def start_server(bundle: Path, port: int = 0, host: str = "127.0.0.1"):
    Handler.bundle = bundle
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _smoke(app, window) -> int:  # pragma: no cover
    import json

    from PySide6.QtCore import QTimer

    state = {"n": 0}

    def tick():
        window.page().runJavaScript("JSON.stringify(globalThis.__demo || {})", 0, done)

    def done(raw):
        info = json.loads(raw) if raw else {}
        if not info.get("connected"):
            state["n"] += 1
            if state["n"] > 80:
                print("[smoke] FAIL: 页面没有连上")
                app.exit(1)
                return
            QTimer.singleShot(300, tick)
            return
        frame = window.window_bridge.state()
        ok = bool(info.get("drag")) and int(info.get("regions") or 0) > 0 and frame.get("width", 0) > 0
        print(f"[smoke] info={info}")
        print(f"[smoke] window={frame}")
        print(f"[smoke] {'PASS' if ok else 'FAIL'}")
        app.exit(0 if ok else 1)

    QTimer.singleShot(900, tick)
    QTimer.singleShot(60000, lambda: (print("[smoke] FAIL: 超时"), app.exit(1)))
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(description="axon-shell 最小示例")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--debugger-port", type=int, default=0)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault(
            "QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage"
        )
    if args.debugger_port:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = f"127.0.0.1:{args.debugger_port}"

    server = start_server(find_axon_bundle(), args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    app = QApplication(sys.argv[:1])
    AxonMagicGUI()
    window = AxonShellWindow(WEB_NAME, url, title="axon-shell 最小示例", size=(980, 680), min_size=(560, 420))
    window.show()
    print(f"[demo] 已打开 {url} (web_name={WEB_NAME})")

    if args.smoke:
        return _smoke(app, window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
