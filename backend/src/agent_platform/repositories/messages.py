"""消息数据读写。"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Message


class MessageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        conversation_id: int,
        role: str,
        content: str,
        attachments: list | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            attachments=attachments,
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def get(self, message_id: int) -> Message | None:
        return self.db.get(Message, message_id)

    def list_by_conversation(self, conversation_id: int) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return list(self.db.scalars(stmt))

    def delete_from(self, conversation_id: int, message_id: int) -> None:
        """删除某条消息及其之后的所有消息（用于「重新生成」从该处重跑）。"""
        self.db.execute(
            delete(Message).where(
                Message.conversation_id == conversation_id,
                Message.id >= message_id,
            )
        )
        self.db.commit()
