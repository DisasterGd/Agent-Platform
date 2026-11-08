"""FastAPI 依赖：数据库会话与当前用户身份。

当前为本地单用户开发模式，用户身份直接取自配置；公网部署前必须替换为真实认证。
"""
from __future__ import annotations

from agent_platform.config import settings
from agent_platform.infrastructure.database.session import get_db

__all__ = ["get_db", "get_current_user_id"]


def get_current_user_id() -> int:
    return settings.dev_user_id
