"""构建便携版单文件 exe（v0.9 发布物）。

用法（仓库根目录）:
    .\\.venv\\Scripts\\python.exe scripts\\build_exe.py

前置:
    - 已装 pyinstaller（cd backend && pip install -e ".[dev]" 会带上）
    - 前端已构建（frontend/dist 存在；否则先 cd frontend && npm install && npm run build）

产物:
    - dist/AgentPlatform.exe   单文件、免安装、双击即用
    - build/                   中间产物（已 gitignore，可删）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "AgentPlatform.spec"
FRONTEND_DIST = ROOT / "frontend" / "dist"


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def main() -> int:
    if not (FRONTEND_DIST / "index.html").exists():
        print("前端未构建：frontend/dist 不存在。请先 cd frontend && npm install && npm run build")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("未安装 pyinstaller。请先：cd backend && pip install -e \".[dev]\"")
        return 1

    return _run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)])


if __name__ == "__main__":
    raise SystemExit(main())
