"""会话分组用例（v0.4.1）：用户自定义分组的增删改。

默认分组（项目 / 任务 / 未分组）不经过本表，由代码依据
group_id → project_id → 是否有任务 → 未分组 的优先级归类。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import ConversationGroup
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.groups import GroupRepository

GROUP_KINDS = ("group", "task")


class GroupService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.groups = GroupRepository(db)
        self.conversations = ConversationRepository(db)

    def create(self, user_id: int, name: str, kind: str = "group") -> ConversationGroup:
        if kind not in GROUP_KINDS:
            raise ValueError("分组类型不合法")
        return self.groups.create(user_id, name.strip() or "未命名分组", kind)

    def list(self, user_id: int) -> list[ConversationGroup]:
        return self.groups.list_by_user(user_id)

    def get(self, group_id: int, user_id: int) -> ConversationGroup | None:
        group = self.groups.get(group_id)
        if group is None or group.user_id != user_id:
            return None
        return group

    def update(self, group_id: int, user_id: int, name: str | None = None) -> ConversationGroup | None:
        if self.get(group_id, user_id) is None:
            return None
        return self.groups.update(group_id, name=name)

    def delete(self, group_id: int, user_id: int) -> bool:
        """删除分组：其中的会话退回默认归类（不删会话）。"""
        if self.get(group_id, user_id) is None:
            return False
        self.conversations.clear_group(group_id)
        return self.groups.delete(group_id)
