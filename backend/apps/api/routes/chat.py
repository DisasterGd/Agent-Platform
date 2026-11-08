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
    created_at: datetime
    updated_at: datetime


class CreateConversationIn(BaseModel):
    title: str = "新会话"


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime


class ChatStreamIn(BaseModel):
    conversation_id: int
    content: str


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return ChatService(db).list_conversations(user_id)


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(
    body: CreateConversationIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return ChatService(db).create_conversation(user_id, body.title)


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
        async for event in service.stream_reply(body.conversation_id, body.content):
            yield to_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
