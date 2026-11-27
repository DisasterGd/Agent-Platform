"""本地项目数据读写（v0.7.4）。与 ProjectRepository 同款风格；全部按 user_id 过滤。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import LocalProject


class LocalProjectRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_user(self, user_id: int) -> list[LocalProject]:
        stmt = (
            select(LocalProject)
            .where(LocalProject.user_id == user_id)
            .order_by(LocalProject.updated_at.desc())
        )
        return list(self.db.scalars(stmt))

    def get(self, project_id: int) -> LocalProject | None:
        return self.db.get(LocalProject, project_id)

    def get_owned(self, project_id: int, user_id: int) -> LocalProject | None:
        project = self.db.get(LocalProject, project_id)
        if project is None or project.user_id != user_id:
            return None
        return project

    def get_by_root(self, user_id: int, root_path: str) -> LocalProject | None:
        stmt = select(LocalProject).where(
            LocalProject.user_id == user_id, LocalProject.root_path == root_path
        )
        return self.db.scalar(stmt)

    def create(self, user_id: int, title: str, root_path: str, allow_write: bool = True) -> LocalProject:
        project = LocalProject(user_id=user_id, title=title[:200], root_path=root_path[:500],
                               allow_write=allow_write)
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update(self, project: LocalProject, title: str | None = None, allow_write: bool | None = None) -> LocalProject:
        if title is not None and title.strip():
            project.title = title.strip()[:200]
        if allow_write is not None:
            project.allow_write = allow_write
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project: LocalProject) -> None:
        # 只删注册行；磁盘文件绝不动，关联会话由 FK ON DELETE SET NULL 保留
        self.db.delete(project)
        self.db.commit()
