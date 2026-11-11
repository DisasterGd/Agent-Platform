"""会话数据读写。"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Conversation


class ConversationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: int, title: str = "新会话") -> Conversation:
        conversation = Conversation(user_id=user_id, title=title)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def list_by_user(self, user_id: int) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list(self.db.scalars(stmt))

    def get(self, conversation_id: int) -> Conversation | None:
        return self.db.get(Conversation, conversation_id)

    def update_title(self, conversation_id: int, title: str) -> Conversation | None:
        conversation = self.db.get(Conversation, conversation_id)
        if conversation is None:
            return None
        conversation.title = title
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def touch(self, conversation_id: int) -> None:
        """更新 updated_at，使最近有消息的会话排到列表顶部。"""
        self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        self.db.commit()
