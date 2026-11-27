from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from agent_platform.config import settings

# v0.8.1：MySQL 连接池按部署规模调参（.env 可覆盖）；SQLite（测试/脚本）不接受 QueuePool 参数，跳过
_engine_kwargs: dict = {"pool_pre_ping": True, "pool_recycle": 1800}
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs["pool_size"] = settings.db_pool_size
    _engine_kwargs["max_overflow"] = settings.db_max_overflow

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
