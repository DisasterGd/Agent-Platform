from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from agent_platform.core.events import to_sse
from agent_platform.services.chat_service import ChatService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["chat"])


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    pinned: bool
    project_id: int | None = None
    group_id: int | None = None
    # v0.4.1 默认分组归类：task=任务模式相关会话（由任务表派生），chat=普通会话
    kind: str = "chat"
    created_at: datetime
    updated_at: datetime


class CreateConversationIn(BaseModel):
    title: str = "新会话"
    project_id: int | None = None  # v0.4：归属项目（None = 未分组）


class UpdateConversationIn(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    # v0.4.1：显式传 null 表示“移出项目 / 移出分组”（model_fields_set 区分未传与传 null）
    project_id: int | None = None
    group_id: int | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime
    attachments: list | None = None
    group_id: int | None = None
    variant_index: int = 0


class AttachmentIn(BaseModel):
    name: str
    url: str
    content_type: str = ""


class ChatStreamIn(BaseModel):
    conversation_id: int
    content: str
    attachments: list[AttachmentIn] = []


class RegenerateIn(BaseModel):
    conversation_id: int
    message_id: int
    content: str | None = None


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    project_id: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    # project_id 省略=全部；"none"=未分组；数字=指定项目
    if project_id is None:
        return ChatService(db).list_conversations(user_id)
    if project_id == "none":
        return ChatService(db).list_conversations(user_id, project_id=None)
    return ChatService(db).list_conversations(user_id, project_id=int(project_id))


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(
    body: CreateConversationIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return ChatService(db).create_conversation(user_id, body.title, body.project_id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def update_conversation(
    conversation_id: int,
    body: UpdateConversationIn,
    db: Session = Depends(get_db),
):
    # 只有请求里显式出现的 project_id / group_id 才会改归属（null=移出）
    move_kwargs: dict = {}
    if "project_id" in body.model_fields_set:
        move_kwargs["project_id"] = body.project_id
    if "group_id" in body.model_fields_set:
        move_kwargs["group_id"] = body.group_id
    try:
        conversation = ChatService(db).update_conversation(
            conversation_id, body.title, body.pinned, **move_kwargs
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
):
    if not ChatService(db).delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="会话不存在")


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: int, db: Session = Depends(get_db)):
    service = ChatService(db)
    if service.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return service.list_messages(conversation_id)


@router.post("/chat/stream")
async def stream_chat(body: ChatStreamIn, db: Session = Depends(get_db)):
    service = ChatService(db)
    if service.get_conversation(body.conversation_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.stream_reply(
            body.conversation_id,
            body.content,
            [a.model_dump() for a in body.attachments],
        ):
            yield to_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/regenerate")
async def regenerate_chat(body: RegenerateIn, db: Session = Depends(get_db)):
    service = ChatService(db)
    if service.get_conversation(body.conversation_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.regenerate_reply(body.conversation_id, body.message_id, body.content):
            yield to_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
