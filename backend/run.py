"""一键启动后端（同时托管已构建的前端）。

- PyCharm 里直接运行本文件即可；或双击仓库根目录的 start.bat（会先跑迁移再调本文件）。
- 后端把 frontend/dist 作为静态站点托管在 http://127.0.0.1:8000，并自动打开浏览器。
- 若目标端口已被监听（通常表示已有一个实例在跑），只打开浏览器、不重复启动。
"""
from __future__ import annotations

import argparse
import socket
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


def _open_browser_after(url: str, delay: float = 1.5) -> None:
    def _open() -> None:
        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Platform 一键启动")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码改动自动重启（默认关闭）")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    print()
    print("=" * 58)
    print("  Agent Platform")
    if FRONTEND_DIST.is_dir():
        print(f"  前端页面：{url}")
    else:
        print("  前端尚未构建：请先 cd frontend && npm run build")
        print("  （或另开终端 cd frontend && npm run dev 走开发模式）")
    print(f"  API 文档：{url}/docs")
    print("  按 Ctrl+C 停止")
    print("=" * 58)
    print()

    if _port_in_use(args.host, args.port):
        print(f"端口 {args.port} 已有进程监听（可能已有一个实例在运行）。")
        print(f"直接打开浏览器访问 {url}。")
        if not args.no_browser:
            _open_browser_after(url, delay=0.5)
        return

    if not args.no_browser:
        _open_browser_after(url)

    uvicorn.run(
        "apps.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(BACKEND_DIR),
    )


if __name__ == "__main__":
    main()
