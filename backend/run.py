"""一键启动后端（同时托管已构建的前端）。

三种用法，同一份代码：
- 开发：PyCharm 直接运行本文件；或双击仓库根目录 start.bat。
- 发布：PyInstaller 把本文件 + frontend/dist + migrations 打成单文件 AgentPlatform.exe，
  双击即启动（首次运行自动补 .env，每次自动跑数据库迁移，自动开浏览器）。
- 目标端口已被监听时只打开浏览器、不重复启动。
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def _repo_root() -> Path:
    """静态资源根：frontend/dist、backend/migrations、.env.example 都在其下。"""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return BACKEND_DIR.parent


def _runtime_dir() -> Path:
    """运行期数据根：.env 与 data/。便携 = exe 旁；开发 = 仓库根。"""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return BACKEND_DIR.parent


def _fail(message: str, code: int = 1) -> None:
    print()
    print(message)
    if FROZEN:
        try:
            input("按回车键退出...")
        except EOFError:
            pass
    sys.exit(code)


def _restrict_env_permissions(env: Path) -> None:
    """.env 后续会写入真实密钥，尽量收紧访问权限（best-effort，失败不影响启动）。

    Windows 没有 chmod 语义，用 icacls 去掉继承、仅保留当前用户/管理员/系统；
    POSIX 下直接 0o600（等价 chmod 600）。
    """
    try:
        if sys.platform == "win32":
            import getpass

            subprocess.run(
                [
                    "icacls",
                    str(env),
                    "/inheritance:r",
                    "/grant:r",
                    f"{getpass.getuser()}:(F)",  # 当前用户
                    "*S-1-5-32-544:(F)",  # Administrators
                    "*S-1-5-18:(F)",  # SYSTEM
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            env.chmod(0o600)
    except Exception as exc:  # noqa: BLE001 — 权限收紧是尽力而为，绝不允许拖垮启动
        print(f"（提示）收紧 .env 权限失败，已忽略：{exc}")


def _ensure_env() -> None:
    env = _runtime_dir() / ".env"
    if env.exists():
        return
    template = _repo_root() / ".env.example"
    if not template.exists():
        _fail("缺少 .env（连内置模板都没有）。请参照仓库 .env.example 手动创建。")
    env.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    _restrict_env_permissions(env)
    print(f"首次运行：已在 {env} 生成配置模板。")
    print("请编辑它（数据库口令 DATABASE_URL、可选的 LLM_API_KEY），然后重新启动。")
    try:
        subprocess.Popen(["notepad.exe", str(env)])
    except OSError:
        pass
    _fail("", code=0)


def _run_migrations() -> None:
    migrations_dir = _repo_root() / "backend" / "migrations"
    ini = _repo_root() / "backend" / "alembic.ini"
    if not (migrations_dir / "env.py").exists():
        return  # 开发环境缺少迁移目录时跳过（可手动 alembic upgrade head）

    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(migrations_dir))
    try:
        command.upgrade(cfg, "head")
        print("数据库迁移：已是最新。")
    except Exception as exc:  # noqa: BLE001 — 迁移失败种类不定，统一拦截后友好提示
        _fail(
            f"数据库迁移失败：{exc}\n"
            "请确认：1) MySQL 已启动；2) 数据库 agent_platform 已创建；3) .env 的 DATABASE_URL 口令正确。"
        )


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

    _ensure_env()
    _run_migrations()

    # .env 与迁移就绪后再导入应用（apps 包只在 backend 目录下可导入；打包后由 PyInstaller 提供）
    from apps.api.main import app
    frontend_dist = _repo_root() / "frontend" / "dist"
    url = f"http://{args.host}:{args.port}"

    print()
    print("=" * 58)
    print("  Agent Platform")
    if frontend_dist.is_dir():
        print(f"  前端页面：{url}")
    else:
        print("  前端尚未构建：请先 cd frontend && npm run build")
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

    if args.reload and not FROZEN:
        # 开发热重载需要 import string（uvicorn 限制）；打包后一律用 app 对象
        uvicorn.run(
            "apps.api.main:app",
            host=args.host,
            port=args.port,
            reload=True,
            app_dir=str(BACKEND_DIR),
        )
    else:
        uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
