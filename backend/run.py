"""一键启动后端（同时托管已构建的前端）。

在 PyCharm 中直接运行本文件即可。后端会把 frontend/dist 作为静态站点
托管在 http://127.0.0.1:8000，无需再单独启动前端开发服务器。
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn  # noqa: E402

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def _open_browser_after(url: str, delay: float = 1.5) -> None:
    def _open() -> None:
        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    print()
    print("=" * 58)
    print("  Agent Platform")
    if FRONTEND_DIST.is_dir():
        print(f"  前端页面：{URL}")
    else:
        print("  前端尚未构建：请先 cd frontend && npm run build")
        print("  （或另开终端 cd frontend && npm run dev 走开发模式）")
    print(f"  API 文档：{URL}/docs")
    print("  按 Ctrl+C 停止")
    print("=" * 58)
    print()

    _open_browser_after(URL)

    uvicorn.run(
        "apps.api.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        app_dir=str(BACKEND_DIR),
    )


if __name__ == "__main__":
    main()
