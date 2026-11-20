"""任务接口（v0.3 任务规划与执行）。

POST /tasks               创建任务（模型生成计划，状态 awaiting_approval）
PUT  /tasks/{id}/steps    审阅阶段编辑计划
POST /tasks/{id}/cancel   取消任务
POST /tasks/{id}/execute  SSE 流式执行（plan_created/step_*/text_delta/task_completed）
GET  /tasks?conversation_id= / GET /tasks/{id}   查询
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from agent_platform.core.events import to_sse
from agent_platform.services.task_service import TaskService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["tasks"])


class TaskStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    idx: int
    title: str
    detail: str
    status: str
    summary: str
    error: str
    artifacts: list | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    conversation_id: int | None
    goal: str
    status: str
    summary: str
    error: str
    created_at: datetime
    updated_at: datetime
    steps: list[TaskStepOut] = []


class CreateTaskIn(BaseModel):
    goal: str
    conversation_id: int | None = None


class StepIn(BaseModel):
    title: str
    detail: str = ""


class ReviseIn(BaseModel):
    steps: list[StepIn]


def _get_owned_task(service: TaskService, task_id: int, user_id: int):
    task = service.get_task(task_id, user_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    body: CreateTaskIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not body.goal.strip():
        raise HTTPException(status_code=400, detail="任务目标不能为空")
    return await TaskService(db).create_task(user_id, body.goal, body.conversation_id)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    conversation_id: int | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    if conversation_id is not None:
        return service.list_by_conversation(conversation_id, user_id)
    return []


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return _get_owned_task(TaskService(db), task_id, user_id)


@router.put("/tasks/{task_id}/steps", response_model=TaskOut)
def revise_task(
    task_id: int,
    body: ReviseIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    _get_owned_task(service, task_id, user_id)
    task = service.revise(task_id, user_id, [s.model_dump() for s in body.steps])
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    _get_owned_task(service, task_id, user_id)
    return service.cancel(task_id, user_id)


@router.post("/tasks/{task_id}/execute")
async def execute_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    _get_owned_task(service, task_id, user_id)

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.execute(task_id, user_id):
            yield to_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
