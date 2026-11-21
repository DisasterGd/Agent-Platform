"""项目用例（v0.4）：左侧项目栏的分组管理。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Project
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.memories import MemoryRepository
from agent_platform.repositories.projects import ProjectRepository


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.conversations = ConversationRepository(db)
        self.memories = MemoryRepository(db)

    def create(self, user_id: int, name: str, description: str = "") -> Project:
        return self.projects.create(user_id, name.strip() or "未命名项目", description.strip())

    def list(self, user_id: int) -> list[Project]:
        return self.projects.list_by_user(user_id)

    def get(self, project_id: int, user_id: int) -> Project | None:
        project = self.projects.get(project_id)
        if project is None or project.user_id != user_id:
            return None
        return project

    def update(
        self,
        project_id: int,
        user_id: int,
        name: str | None = None,
        description: str | None = None,
        pinned: bool | None = None,
    ) -> Project | None:
        if self.get(project_id, user_id) is None:
            return None
        return self.projects.update(project_id, name=name, description=description, pinned=pinned)

    def delete(self, project_id: int, user_id: int) -> bool:
        """删除项目：其项目记忆一并删除，会话退回“未分组”（不删会话）。"""
        if self.get(project_id, user_id) is None:
            return False
        self.memories.delete_by_project(project_id)
        self.conversations.clear_project(project_id)
        return self.projects.delete(project_id)
