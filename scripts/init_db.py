"""初始化本地开发数据：创建表（幂等）并写入开发用户。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import select  # noqa: E402

from agent_platform.config import settings  # noqa: E402
from agent_platform.infrastructure.database import models  # noqa: E402,F401
from agent_platform.infrastructure.database.base import Base  # noqa: E402
from agent_platform.infrastructure.database.session import SessionLocal, engine  # noqa: E402


def main() -> None:
    # 幂等：表已存在则跳过。正式迁移请用 `alembic upgrade head`。
    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        user = db.scalar(select(models.User).where(models.User.id == settings.dev_user_id))
        if user is None:
            db.add(models.User(id=settings.dev_user_id, username="developer"))
            db.commit()
            print(f"已创建开发用户 id={settings.dev_user_id}")
        else:
            print(f"开发用户已存在 id={settings.dev_user_id}，跳过")


if __name__ == "__main__":
    main()
