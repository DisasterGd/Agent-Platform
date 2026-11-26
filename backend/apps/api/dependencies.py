"""FastAPI 依赖：数据库会话与当前用户身份（v0.7 双模式）。

get_current_user_id 是全系统唯一身份来源（隔离纪律 #1：任何请求体/查询参数里的 user_id 一律忽略）：
- local（默认）：优先解析 ap_session cookie（设置页「账号管理」登录后即切换到该账号的数据，
  支持"随时登录、取回已保存数据"）；无 cookie/会话无效 → dev_user_id，行为与 v0.6 完全一致；
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
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if settings.auth_mode == "local":
        if token:
            user = auth_service.resolve_session(db, token)
            if user is not None:
                return user.id  # 本地已登录：切换到该账号（会话 30 天滑动有效）
        return settings.dev_user_id  # 未登录/会话失效：本地默认身份，行为同 v0.6
    user = auth_service.resolve_session(db, token or "")
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user.id
