"""把 examples/files 打包成可双击的程序（onedir，不是 onefile）。

onefile 每次启动都要把 200MB+ 解到临时目录，冷启动很慢；onedir 解压一次就完事。
PyInstaller 不能交叉编译：要 Windows 的 exe 就在 Windows 上跑这个脚本，
或者用仓库里的 `.github/workflows/windows-exe.yml`。

    python tools/build_exe.py                 # 产物在 dist/AxonFiles/
    python tools/build_exe.py --clean         # 先删旧产物
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "files"
SEP = ";" if sys.platform == "win32" else ":"


def find_bundle() -> Path:
    candidates = [
        DEMO / "vendor" / "axon.umd.cjs",
        DEMO / "node_modules" / "axon-gui" / "dist" / "axon.umd.cjs",
        Path.cwd() / "node_modules" / "axon-gui" / "dist" / "axon.umd.cjs",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("找不到 axon.umd.cjs：先在 examples/files 里 `npm install axon-gui@1.0.0`")


def import_roots() -> list[Path]:
    """可编辑安装（pip install -e）时 PyInstaller 找不到包，把它们的父目录加进 --paths。"""
    roots: list[Path] = [ROOT / "src"]
    for name in ("axon", "axon_shell"):
        spec = importlib.util.find_spec(name)
        locations = getattr(spec, "submodule_search_locations", None) if spec else None
        if locations:
            parent = Path(next(iter(locations))).resolve().parent
            if parent not in roots:
                roots.append(parent)
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包 examples/files")
    parser.add_argument("--name", default="AxonFiles")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)

    bundle = find_bundle()
    assets = ROOT / "src" / "axon_shell" / "assets"
    icon = assets / ("axon.ico" if sys.platform == "win32" else "icon-256.png")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onedir", "--windowed",
        "--name", args.name,
    ]
    for root in import_roots():
        cmd += ["--paths", str(root)]
    cmd += [
        "--add-data", f"{DEMO / 'web'}{SEP}web",
        "--add-data", f"{DEMO / 'workspace'}{SEP}workspace",
        "--add-data", f"{bundle}{SEP}vendor",
        "--add-data", f"{ROOT / 'assets' / 'axon-mark.svg'}{SEP}brand.svg",
        # 皮肤随包走，assets_dir() 在冻结后也能指到
        "--collect-data", "axon_shell",
    ]
    if icon.is_file():
        cmd += ["--icon", str(icon)]
    cmd.append(str(DEMO / "main.py"))

    if args.clean:
        shutil.rmtree(ROOT / "build", ignore_errors=True)
        shutil.rmtree(ROOT / "dist", ignore_errors=True)

    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"[build] done: {ROOT / 'dist' / args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
