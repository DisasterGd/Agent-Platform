"""消息数据读写。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Message


class MessageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, conversation_id: int, role: str, content: str) -> Message:
        message = Message(conversation_id=conversation_id, role=role, content=content)
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def list_by_conversation(self, conversation_id: int) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return list(self.db.scalars(stmt))
