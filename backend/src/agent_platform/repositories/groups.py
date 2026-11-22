"""用户自定义会话分组数据读写（v0.4.1 分组优化）。"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import ConversationGroup


class GroupRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: int, name: str, kind: str = "group") -> ConversationGroup:
        group = ConversationGroup(user_id=user_id, name=name[:200] or "未命名分组", kind=kind)
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)
        return group

    def list_by_user(self, user_id: int) -> list[ConversationGroup]:
        stmt = (
            select(ConversationGroup)
            .where(ConversationGroup.user_id == user_id)
            .order_by(ConversationGroup.created_at, ConversationGroup.id)
        )
        return list(self.db.scalars(stmt))

    def get(self, group_id: int) -> ConversationGroup | None:
        return self.db.get(ConversationGroup, group_id)

    def update(self, group_id: int, name: str | None = None) -> ConversationGroup | None:
        group = self.db.get(ConversationGroup, group_id)
        if group is None:
            return None
        if name is not None and name.strip():
            group.name = name.strip()[:200]
        self.db.commit()
        self.db.refresh(group)
        return group

    def delete(self, group_id: int) -> bool:
        group = self.db.get(ConversationGroup, group_id)
        if group is None:
            return False
        self.db.delete(group)
        self.db.commit()
        return True

    def search(self, user_id: int, keyword: str, limit: int = 20) -> list[ConversationGroup]:
        """分组名命中关键词（搜索弹窗“分组”范围）。"""
        like = f"%{keyword}%"
        stmt = (
            select(ConversationGroup)
            .where(ConversationGroup.user_id == user_id, or_(ConversationGroup.name.like(like)))
            .order_by(ConversationGroup.created_at, ConversationGroup.id)
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
