"""全局搜索接口（v0.4.1）：左侧“搜索”弹窗的检索入口。

GET /api/search?q=关键词&scope=all|conversations|tasks|projects|groups
会话结果附带最近一条消息摘要；任务结果附带步骤进度；其余由前端补充展示信息。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from agent_platform.services.search_service import SearchService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["search"])

Scope = Literal["all", "conversations", "tasks", "projects", "groups"]


class ConversationHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    pinned: bool
    project_id: int | None = None
    group_id: int | None = None
    kind: str = "chat"
    created_at: datetime
    updated_at: datetime
    snippet: str = ""


class TaskHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int | None
    project_id: int | None = None
    goal: str
    status: str
    updated_at: datetime
    steps_total: int = 0
    steps_done: int = 0


class ProjectHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    pinned: bool
    updated_at: datetime


class GroupHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    kind: str = "group"
    created_at: datetime
    updated_at: datetime


class SearchResultsOut(BaseModel):
    conversations: list[ConversationHit] = []
    tasks: list[TaskHit] = []
    projects: list[ProjectHit] = []
    groups: list[GroupHit] = []


@router.get("/search", response_model=SearchResultsOut)
def search(
    q: str = "",
    scope: Scope = "all",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    results = SearchService(db).search(user_id, q, scope)
    return SearchResultsOut(
        conversations=[
            ConversationHit.model_validate(conv).model_copy(update={"snippet": snippet})
            for conv, snippet in results.conversations
        ],
        tasks=[
            TaskHit(
                id=t.id,
                conversation_id=t.conversation_id,
                project_id=t.project_id,
                goal=t.goal,
                status=t.status,
                updated_at=t.updated_at,
                steps_total=len(t.steps),
                steps_done=sum(1 for s in t.steps if s.status == "done"),
            )
            for t in results.tasks
        ],
        projects=[ProjectHit.model_validate(p) for p in results.projects],
        groups=[GroupHit.model_validate(g) for g in results.groups],
    )
