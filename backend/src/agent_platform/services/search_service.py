"""全局搜索用例（v0.4.1）：搜索弹窗的分范围检索。

scope: all / conversations / tasks / projects / groups。
会话结果附带“最近的相关信息”（最后一条消息摘要），其余结果带原始对象，
命中数/状态等展示信息由前端基于已有列表拼装。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import (
    Conversation,
    ConversationGroup,
    Project,
    Task,
)
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.groups import GroupRepository
from agent_platform.repositories.messages import MessageRepository
from agent_platform.repositories.projects import ProjectRepository
from agent_platform.repositories.tasks import TaskRepository

SCOPES = ("all", "conversations", "tasks", "projects", "groups")


@dataclass
class SearchResults:
    conversations: list[tuple[Conversation, str]] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    groups: list[ConversationGroup] = field(default_factory=list)


class SearchService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)
        self.tasks = TaskRepository(db)
        self.projects = ProjectRepository(db)
        self.groups = GroupRepository(db)

    def search(self, user_id: int, keyword: str, scope: str = "all") -> SearchResults:
        keyword = keyword.strip()
        out = SearchResults()
        if not keyword or scope not in SCOPES:
            return out
        limit = 8 if scope == "all" else 20

        if scope in ("all", "conversations"):
            convs = self.conversations.search(user_id, keyword, limit=limit)
            out.conversations = [(c, self.messages.latest_snippet(c.id)) for c in convs]
        if scope in ("all", "tasks"):
            out.tasks = self.tasks.search(user_id, keyword, limit=limit)
        if scope in ("all", "projects"):
            out.projects = self.projects.search(user_id, keyword, limit=limit)
        if scope in ("all", "groups"):
            out.groups = self.groups.search(user_id, keyword, limit=limit)
        return out
