"""会话数据读写。"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Conversation


class ConversationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: int, title: str = "新会话", project_id: int | None = None) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title, project_id=project_id)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def list_by_user(self, user_id: int, project_id: int | None = ..., pinned_first: bool = True) -> list[Conversation]:
        """project_id=... 表示不过滤；传 int 按项目过滤；传 None 只看“未分组”会话。"""
        stmt = select(Conversation).where(Conversation.user_id == user_id)
        if project_id is not ...:
            stmt = stmt.where(Conversation.project_id == project_id)
        if pinned_first:
            stmt = stmt.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
        else:
            stmt = stmt.order_by(Conversation.updated_at.desc())
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

    def update(self, conversation_id: int, title: str | None = None, pinned: bool | None = None) -> Conversation | None:
        conversation = self.db.get(Conversation, conversation_id)
        if conversation is None:
            return None
        if title is not None:
            conversation.title = title
        if pinned is not None:
            conversation.pinned = pinned
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def delete(self, conversation_id: int) -> bool:
        conversation = self.db.get(Conversation, conversation_id)
        if conversation is None:
            return False
        self.db.delete(conversation)
        self.db.commit()
        return True

    def touch(self, conversation_id: int) -> None:
        """更新 updated_at，使最近有消息的会话排到列表顶部。"""
        self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        self.db.commit()

    def update_summary(self, conversation_id: int, summary: str, covered_id: int) -> None:
        """v0.4 会话记忆：保存历史压缩摘要与其覆盖到的最大消息 id。"""
        conversation = self.db.get(Conversation, conversation_id)
        if conversation is None:
            return
        conversation.summary = summary
        conversation.summary_covered_id = covered_id
        self.db.commit()

    def clear_project(self, project_id: int) -> int:
        """项目删除后把其会话退回“未分组”。"""
        rows = list(self.db.scalars(select(Conversation).where(Conversation.project_id == project_id)))
        for row in rows:
            row.project_id = None
        self.db.commit()
        return len(rows)

    def set_project(self, conversation_id: int, project_id: int | None) -> None:
        conversation = self.db.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.project_id = project_id
            self.db.commit()
