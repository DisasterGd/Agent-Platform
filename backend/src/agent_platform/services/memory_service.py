"""记忆用例（v0.4）：设置界面的记忆管理 + 运行时注入入口。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Memory
from agent_platform.repositories.memories import MemoryRepository


class MemoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.memories = MemoryRepository(db)

    def list(
        self,
        user_id: int,
        scope: str | None = None,
        project_id: int | None = None,
        enabled_only: bool = False,
    ) -> list[Memory]:
        return self.memories.list(user_id, scope=scope, project_id=project_id, enabled_only=enabled_only)

    def create(
        self,
        user_id: int,
        content: str,
        scope: str = "global",
        project_id: int | None = None,
        category: str = "其他",
        title: str = "",
    ) -> Memory | None:
        content = content.strip()
        if not content:
            return None
        scope = scope if scope in ("global", "project") else "global"
        if scope == "project" and project_id is None:
            return None
        # 手动添加视为“用户明确要求记住”（source=explicit），标题相同则更新
        existing = self.memories.find_similar(user_id, scope, project_id, title)
        if existing is not None:
            return self.memories.update(
                existing.id, content=content, category=category[:50] or "其他", source="explicit"
            )
        return self.memories.create(
            user_id,
            content=content,
            scope=scope,
            project_id=project_id,
            category=category,
            title=title.strip()[:200] or content[:20],
            source="explicit",
        )

    def _owned(self, memory_id: int, user_id: int) -> Memory | None:
        memory = self.memories.get(memory_id)
        if memory is None or memory.user_id != user_id:
            return None
        return memory

    def update(
        self,
        memory_id: int,
        user_id: int,
        *,
        title: str | None = None,
        content: str | None = None,
        category: str | None = None,
        enabled: bool | None = None,
    ) -> Memory | None:
        if self._owned(memory_id, user_id) is None:
            return None
        return self.memories.update(
            memory_id,
            title=title.strip()[:200] if title is not None and title.strip() else None,
            content=content.strip() if content is not None and content.strip() else None,
            category=category[:50] if category else None,
            enabled=enabled,
        )

    def delete(self, memory_id: int, user_id: int) -> bool:
        if self._owned(memory_id, user_id) is None:
            return False
        return self.memories.delete(memory_id)
