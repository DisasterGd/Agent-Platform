"""管理员接口（v0.7，最小三件套）：用户列表 / 停用启用 / 聚合统计。

权限边界（设计文档 3.7）：admin 只管账号生命周期与聚合统计，**不获得读取他人业务数据的权限**
（会话/文件/记忆仍严格隔离）。首个 admin 由 .env 的 ADMIN_EMAIL 指定（该邮箱注册时自动 is_admin=1）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import (
    Conversation,
    KnowledgeChunk,
    Message,
    Task,
    User,
)
from agent_platform.infrastructure.storage.local import get_storage
from agent_platform.repositories.users import UserRepository
from agent_platform.services import auth_service
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["admin"])


def require_admin(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> User:
    """非管理员一律 403（不暴露管理面存在与否的判断细节）。"""
    user = UserRepository(db).get(user_id)
    if user is None or not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


class AdminUserOut(BaseModel):
    """用户列表项：只含账号生命周期字段，不含任何业务数据。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str | None = None
    display_name: str = ""
    is_admin: bool
    status: str
    created_at: datetime
    last_login_at: datetime | None = None


class AdminUserPatch(BaseModel):
    status: str | None = None  # active / disabled（停用即撤销全部 session——踢下线）


class StatsOut(BaseModel):
    users_total: int
    users_by_status: dict[str, int]
    conversations: int
    messages: int
    tasks: int
    knowledge_chunks: int
    disk_usage: dict[str, int]  # {uploads, generated} 字节数（全库所有用户目录合计）


@router.get("/admin/users", response_model=list[AdminUserOut])
def list_users(
    q: str | None = Query(None, description="按 email/显示名/用户名模糊搜索"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[User]:
    return UserRepository(db).search(q, limit=limit, offset=offset)


@router.get("/admin/users/count")
def count_users(
    q: str | None = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return {"total": UserRepository(db).count_all(q)}


@router.patch("/admin/users/{user_id}", response_model=AdminUserOut)
def patch_user(
    user_id: int,
    body: AdminUserPatch,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    """停用/启用。停用即时撤销该用户全部会话（下一请求即 401 踢下线）；不能停用自己。"""
    if body.status not in ("active", "disabled"):
        raise HTTPException(status_code=400, detail="status 只能是 active 或 disabled")
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能停用自己的账号")
    user = UserRepository(db).set_status(user_id, body.status)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.status == "disabled":
        # 停用即踢下线：撤销全部会话，该用户所有在途请求下一个校验点即 401
        auth_service.revoke_all_sessions(db, user_id)
    return user


@router.get("/admin/stats", response_model=StatsOut)
def stats(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """聚合统计：用户数、各表行数、磁盘占用（admin 不接触任何业务数据内容）。"""

    def _count(model) -> int:
        return int(db.execute(select(func.count(model.id))).scalar_one())

    return {
        "users_total": _count(User),
        "users_by_status": UserRepository(db).count_by_status(),
        "conversations": _count(Conversation),
        "messages": _count(Message),
        "tasks": _count(Task),
        "knowledge_chunks": _count(KnowledgeChunk),
        "disk_usage": get_storage().usage(),
    }
