"""会话分组接口（v0.4.1）：用户自定义分组的增删改查。

只管理“自定义分组”；默认分组（项目 / 任务 / 未分组）由代码归类，不建记录。
会话归属通过 PATCH /api/conversations/{id} 的 group_id 字段设置。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from agent_platform.services.group_service import GroupService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["groups"])


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    name: str
    created_at: datetime
    updated_at: datetime


class CreateGroupIn(BaseModel):
    name: str


class UpdateGroupIn(BaseModel):
    name: str | None = None


@router.get("/groups", response_model=list[GroupOut])
def list_groups(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return GroupService(db).list(user_id)


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(
    body: CreateGroupIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="分组名称不能为空")
    return GroupService(db).create(user_id, body.name)


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: int,
    body: UpdateGroupIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    group = GroupService(db).update(group_id, user_id, body.name)
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    return group


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(
    group_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not GroupService(db).delete(group_id, user_id):
        raise HTTPException(status_code=404, detail="分组不存在")
