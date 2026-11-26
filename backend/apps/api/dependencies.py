"""FastAPI 依赖：数据库会话与当前用户身份（v0.7 双模式）。

get_current_user_id 是全系统唯一身份来源（隔离纪律 #1：任何请求体/查询参数里的 user_id 一律忽略）：
- local（默认）：settings.dev_user_id，行为与 v0.6 完全一致；
- cloud：解析 ap_session cookie → sessions 表校验（撤销/过期/账号状态）→ 滑动续期；
  未登录/无效一律 401，路由层零改动（约 38 处都经 Depends 注入）。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.infrastructure.database.session import get_db
from agent_platform.services import auth_service

__all__ = ["get_current_user_id", "get_db"]


def get_current_user_id(request: Request, db: Session = Depends(get_db)) -> int:
    if settings.auth_mode == "local":
        return settings.dev_user_id
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    user = auth_service.resolve_session(db, token or "")
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user.id
