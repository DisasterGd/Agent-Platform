"""记忆接口（v0.4）：设置界面的记忆查看/编辑/启停/删除。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from agent_platform.services.memory_service import MemoryService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["memories"])


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    scope: str
    project_id: int | None
    category: str
    title: str
    content: str
    source: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CreateMemoryIn(BaseModel):
    content: str
    scope: str = "global"          # global | project
    project_id: int | None = None
    category: str = "其他"
    title: str = ""


class UpdateMemoryIn(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    enabled: bool | None = None


@router.get("/memories", response_model=list[MemoryOut])
def list_memories(
    scope: str | None = None,
    project_id: int | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return MemoryService(db).list(user_id, scope=scope, project_id=project_id)


@router.post("/memories", response_model=MemoryOut, status_code=201)
def create_memory(
    body: CreateMemoryIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    memory = MemoryService(db).create(
        user_id, body.content, body.scope, body.project_id, body.category, body.title
    )
    if memory is None:
        raise HTTPException(status_code=400, detail="记忆内容不能为空（项目记忆需指定项目）")
    return memory


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: int,
    body: UpdateMemoryIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    memory = MemoryService(db).update(
        memory_id, user_id,
        title=body.title, content=body.content, category=body.category, enabled=body.enabled,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return memory


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(
    memory_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not MemoryService(db).delete(memory_id, user_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
