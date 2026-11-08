"""数据库连接检查：验证 MySQL 连接与表结构。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import text  # noqa: E402

from agent_platform.infrastructure.database.session import engine  # noqa: E402


def main() -> None:
    with engine.connect() as conn:
        db_name, version = conn.execute(text("SELECT DATABASE(), VERSION()")).fetchone()
        print(f"已连接 MySQL 数据库：{db_name}，版本：{version}")
        tables = [row[0] for row in conn.execute(text("SHOW TABLES"))]
        print(f"现有表：{tables}")


if __name__ == "__main__":
    main()
