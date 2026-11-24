"""示例：用 axon-shell 搭一个「文件浏览器」——VSCode 那种外观，但只有 200 行胶水。

    cd examples/files
    ../../.venv/bin/python main.py                 # 需要 axon-gui 与 axon-shell 可 import
    ../../.venv/bin/python main.py --smoke         # 无头自检
    ../../.venv/bin/python main.py --workspace /tmp/foo

外观全部来自 `axon_shell.assets/shell.css` + `shell.js`；这份文件只做两件事：
1. 把工作区目录读写能力暴露成 `Axon.Files.*`；
2. 起一个静态服务，把页面、皮肤、axon 的 UMD 产物一起发出去。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# PyInstaller 会把数据解到 _MEIPASS；直接跑脚本时就是本目录。
FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
WEB_DIR = BASE_DIR / "web"
BRAND_FILE = BASE_DIR / "brand.svg" if FROZEN else BASE_DIR.parent.parent / "assets" / "axon-mark.svg"


def _default_workspace() -> Path:
    """冻结后不能写进解包目录（重启就没了），所以示例文件复制到用户目录。"""
    if not FROZEN:
        return BASE_DIR / "workspace"
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "axon-shell-demo"
    target = root / "workspace"
    if not target.exists():
        shutil.copytree(BASE_DIR / "workspace", target)
    return target


WORKSPACE = Path(os.environ.get("AXON_FILES_WORKSPACE") or _default_workspace()).resolve()

WEB_NAME = "FilesDemo"

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from axon import AxonController, AxonMagicGUI  # noqa: E402
from axon_shell import AxonShellWindow, assets_dir  # noqa: E402

SHELL_ASSETS = Path(assets_dir())


def find_axon_bundle() -> Path:
    """优先用已安装的 axon-gui 的 dist，其次找本仓库构建出来的那份。"""
    candidates = [
        BASE_DIR / "vendor" / "axon.umd.cjs",
        BASE_DIR / "vendor-axon" / "axon.umd.cjs",
        BASE_DIR / "node_modules" / "axon-gui" / "dist" / "axon.umd.cjs",
        Path.cwd() / "node_modules" / "axon-gui" / "dist" / "axon.umd.cjs",
        BASE_DIR.parent.parent / "core-js" / "dist" / "axon.umd.cjs",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "找不到 axon.umd.cjs：先 `npm install axon-gui`，"
        "或把 node_modules/axon-gui/dist/axon.umd.cjs 复制到 examples/files/vendor/。"
    )


class Handler(SimpleHTTPRequestHandler):
    """静态服务：多挂 /vendor（axon 产物与图标）与 /axon-shell（皮肤）。"""

    bundle = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _send_file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/vendor/axon.umd.cjs", "/vendor/axon.js"):
            return self._send_file(self.bundle, "text/javascript; charset=utf-8")
        if path == "/brand.svg":
            return self._send_file(BRAND_FILE, "image/svg+xml")
        if path.startswith("/axon-shell/"):
            name = path.rsplit("/", 1)[-1]
            if name in ("shell.css", "shell.js"):
                kind = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
                return self._send_file(SHELL_ASSETS / name, kind)
            self.send_error(404)
            return
        return super().do_GET()

    def log_message(self, fmt, *args):  # 静音
        pass


def start_server(bundle: Path, port: int = 0, host: str = "127.0.0.1"):
    Handler.bundle = bundle
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# ── 工作区 ←→ 网页 ──────────────────────────────────────────────────────────
def _safe(rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").strip("/")
    target = (WORKSPACE / rel).resolve()
    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise ValueError(f"路径越界：{rel}")
    return target


def _entry(path: Path) -> dict:
    return {
        "name": path.name,
        "path": path.relative_to(WORKSPACE).as_posix(),
        "isDir": path.is_dir(),
        "size": 0 if path.is_dir() else path.stat().st_size,
    }


@AxonController(WEB_NAME, id="Files")
class FilesController:
    def list_dir(self, rel: str = "") -> dict:
        target = _safe(rel)
        if not target.is_dir():
            raise ValueError(f"不是目录：{rel}")
        entries = sorted(
            (_entry(p) for p in target.iterdir() if p.name != "__pycache__"),
            key=lambda item: (not item["isDir"], item["name"].lower()),
        )
        return {"path": target.relative_to(WORKSPACE).as_posix(), "entries": entries}

    def read_file(self, rel: str) -> dict:
        target = _safe(rel)
        if not target.is_file():
            raise ValueError(f"不是文件：{rel}")
        return {
            "path": target.relative_to(WORKSPACE).as_posix(),
            "content": target.read_text(encoding="utf-8", errors="replace"),
        }

    def write_file(self, rel: str, content: str) -> dict:
        target = _safe(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        target.write_bytes(data)
        return {"path": target.relative_to(WORKSPACE).as_posix(), "bytes": len(data)}

    def create_file(self, rel_dir: str, name: str) -> dict:
        target = _safe(f"{rel_dir}/{name}" if rel_dir else name)
        if target.exists():
            raise ValueError(f"已存在：{name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
        return _entry(target)

    def create_dir(self, rel_dir: str, name: str) -> dict:
        target = _safe(f"{rel_dir}/{name}" if rel_dir else name)
        if target.exists():
            raise ValueError(f"已存在：{name}")
        target.mkdir(parents=True)
        return _entry(target)

    def rename(self, rel: str, new_name: str) -> dict:
        target = _safe(rel)
        if not new_name.strip() or "/" in new_name:
            raise ValueError("名字不合法")
        renamed = target.with_name(new_name)
        if renamed.exists():
            raise ValueError(f"已存在：{new_name}")
        target.rename(renamed)
        return _entry(renamed)

    def delete(self, rel: str) -> dict:
        target = _safe(rel)
        if target.is_dir():
            for child in sorted(target.rglob("*"), reverse=True):
                child.unlink() if child.is_file() else child.rmdir()
            target.rmdir()
        elif target.exists():
            target.unlink()
        return {"path": rel, "deleted": True}

    def reveal(self, rel: str) -> dict:
        target = _safe(rel)
        folder = target if target.is_dir() else target.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        return {"path": str(folder)}

    def about(self) -> dict:
        from PySide6 import __version__ as qt_version

        return {
            "python": sys.version.split()[0],
            "qt": qt_version,
            "platform": sys.platform,
            "workspace": str(WORKSPACE),
            "shell": "axon-shell",
        }


# ── 启动 ────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="axon-shell 文件浏览器示例")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--debugger-port", type=int, default=None)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)

    global WORKSPACE
    if args.workspace:
        WORKSPACE = Path(args.workspace).expanduser().resolve()
        os.environ["AXON_FILES_WORKSPACE"] = str(WORKSPACE)
    WORKSPACE.mkdir(parents=True, exist_ok=True)

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
    window = AxonShellWindow(
        WEB_NAME,
        url,
        title="Files · axon-shell",
        size=(1240, 800),
        min_size=(880, 560),
    )
    window.show()
    print(f"[files] 已打开 {url} (web_name={WEB_NAME}, workspace={WORKSPACE})")

    if args.smoke:
        return _smoke(app, window)
    return app.exec()


def _smoke(app, window) -> int:  # pragma: no cover
    import json as _json

    from PySide6.QtCore import QTimer

    state = {"n": 0}

    def tick():
        window.page().runJavaScript("JSON.stringify(globalThis.__files || {})", 0, done)

    def done(raw):
        info = _json.loads(raw) if raw else {}
        if not info:
            state["n"] += 1
            if state["n"] > 60:
                print("[smoke] FAIL: 页面没有响应")
                app.exit(1)
                return
            QTimer.singleShot(300, tick)
            return
        ok = bool(info.get("connected")) and info.get("chrome") and info.get("rows", 0) > 0
        print(f"[smoke] info={info}")
        frame = window.window_bridge.state()
        print(f"[smoke] window={frame}")
        ok = ok and frame.get("width", 0) > 0
        print(f"[smoke] {'PASS' if ok else 'FAIL'}")
        app.exit(0 if ok else 1)

    QTimer.singleShot(1200, tick)
    QTimer.singleShot(60000, lambda: (print("[smoke] FAIL: 超时"), app.exit(1)))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
