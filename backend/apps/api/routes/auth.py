"""身份认证占位（v0.7 实现真实登录注册）。

当前返回本地开发用户，仅用于调试，不是认证。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.dependencies import get_current_user_id

router = APIRouter(tags=["auth"])


@router.get("/auth/me")
def me(user_id: int = Depends(get_current_user_id)) -> dict:
    return {"id": user_id, "username": "developer"}
