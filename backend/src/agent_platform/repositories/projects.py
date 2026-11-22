"""项目数据读写（v0.4）。"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Project


class ProjectRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: int, name: str, description: str = "") -> Project:
        project = Project(user_id=user_id, name=name[:200] or "未命名项目", description=description)
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def list_by_user(self, user_id: int) -> list[Project]:
        stmt = (
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.pinned.desc(), Project.updated_at.desc())
        )
        return list(self.db.scalars(stmt))

    def get(self, project_id: int) -> Project | None:
        return self.db.get(Project, project_id)

    def update(
        self,
        project_id: int,
        name: str | None = None,
        description: str | None = None,
        pinned: bool | None = None,
    ) -> Project | None:
        project = self.db.get(Project, project_id)
        if project is None:
            return None
        if name is not None and name.strip():
            project.name = name.strip()[:200]
        if description is not None:
            project.description = description
        if pinned is not None:
            project.pinned = pinned
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project_id: int) -> bool:
        project = self.db.get(Project, project_id)
        if project is None:
            return False
        self.db.delete(project)
        self.db.commit()
        return True

    def search(self, user_id: int, keyword: str, limit: int = 20) -> list[Project]:
        """名称或描述命中关键词（搜索弹窗“项目”范围）。"""
        like = f"%{keyword}%"
        stmt = (
            select(Project)
            .where(Project.user_id == user_id, or_(Project.name.like(like), Project.description.like(like)))
            .order_by(Project.pinned.desc(), Project.updated_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
