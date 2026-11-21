"""长期记忆数据读写（v0.4）。

持久化≠作用域：scope 决定记忆在哪里生效（全局跨项目 / 单项目），
检索一律先按作用域过滤，再进入上下文注入或列表展示。
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Memory


class MemoryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        user_id: int,
        content: str,
        scope: str = "global",
        project_id: int | None = None,
        category: str = "其他",
        title: str = "",
        source: str = "auto",
    ) -> Memory:
        memory = Memory(
            user_id=user_id,
            scope=scope,
            project_id=project_id if scope == "project" else None,
            category=category[:50] or "其他",
            title=title[:200],
            content=content,
            source=source,
        )
        self.db.add(memory)
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def get(self, memory_id: int) -> Memory | None:
        return self.db.get(Memory, memory_id)

    def list(
        self,
        user_id: int,
        scope: str | None = None,
        project_id: int | None = None,
        enabled_only: bool = False,
    ) -> list[Memory]:
        stmt = select(Memory).where(Memory.user_id == user_id)
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        if project_id is not None:
            stmt = stmt.where(Memory.project_id == project_id)
        if enabled_only:
            stmt = stmt.where(Memory.enabled.is_(True))
        stmt = stmt.order_by(Memory.updated_at.desc(), Memory.id.desc())
        return list(self.db.scalars(stmt))

    def list_for_context(self, user_id: int, project_id: int | None) -> list[Memory]:
        """上下文注入检索：启用的全局记忆 + 当前项目的启用记忆。"""
        stmt = select(Memory).where(Memory.user_id == user_id, Memory.enabled.is_(True))
        if project_id is None:
            stmt = stmt.where(Memory.scope == "global")
        else:
            stmt = stmt.where(
                or_(
                    Memory.scope == "global",
                    (Memory.scope == "project") & (Memory.project_id == project_id),
                )
            )
        # 用户要求记住的（explicit）优先展示，其次按更新时间
        stmt = stmt.order_by(Memory.source.asc(), Memory.updated_at.desc(), Memory.id.desc())
        return list(self.db.scalars(stmt))

    def find_similar(self, user_id: int, scope: str, project_id: int | None, title: str) -> Memory | None:
        """按标题查重（去归一化），供提炼时合并同题记忆。"""
        target = (title or "").strip().lower()
        if not target:
            return None
        rows = self.list(user_id, scope=scope, project_id=project_id if scope == "project" else None)
        for m in rows:
            if (m.title or "").strip().lower() == target:
                return m
        return None

    def update(self, memory_id: int, **fields: object) -> Memory | None:
        memory = self.db.get(Memory, memory_id)
        if memory is None:
            return None
        for key, value in fields.items():
            if value is None:
                continue
            setattr(memory, key, value)
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def delete(self, memory_id: int) -> bool:
        memory = self.db.get(Memory, memory_id)
        if memory is None:
            return False
        self.db.delete(memory)
        self.db.commit()
        return True

    def delete_by_project(self, project_id: int) -> int:
        """项目删除时显式清理其项目记忆（不依赖数据库级联，sqlite 行为一致）。"""
        rows = list(self.db.scalars(select(Memory).where(Memory.project_id == project_id)))
        for row in rows:
            self.db.delete(row)
        self.db.commit()
        return len(rows)
