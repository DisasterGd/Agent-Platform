"""v0.7 存量文件迁移脚本：把 data/{uploads,generated} 根目录的历史文件搬入 u{user_id}/ 子目录。

用法（在 backend/ 目录下）：
    ..\\.venv\\Scripts\\python.exe scripts\\migrate_files_to_user_dirs.py           # 搬给 dev 用户（默认）
    ..\\.venv\\Scripts\\python.exe scripts\\migrate_files_to_user_dirs.py --user 3  # 搬给指定用户

幂等可重复执行：目标同名文件已存在则跳过（不覆盖）；应用启动时也会自动执行一次（dev 用户）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR / "src"))

from agent_platform.config import settings
from agent_platform.infrastructure.storage.migrate import (
    migrate_root_files_to_user_dirs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="把根目录遗留文件搬入 per-user 子目录（v0.7）")
    parser.add_argument("--user", type=int, default=settings.dev_user_id, help="目标用户 id（默认 dev 用户）")
    args = parser.parse_args()
    moved = migrate_root_files_to_user_dirs(args.user)
    print(f"已把 {moved} 个文件搬入 u{args.user}/（跳过的同名文件保留在原处）")


if __name__ == "__main__":
    main()
