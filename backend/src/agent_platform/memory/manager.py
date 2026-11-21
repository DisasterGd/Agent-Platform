"""记忆管理器（v0.4）：三级记忆的统一入口，供服务层调用。

- 会话记忆（ConversationMemory）：超长历史自动压缩为摘要；
- 长期记忆（LongTermMemory）：全局 + 项目，检索注入 / 对话后提炼。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agent_platform.core.context import build_context
from agent_platform.core.events import Event, context_compressed, memory_saved
from agent_platform.infrastructure.database.models import Conversation, Project
from agent_platform.memory.conversation import ConversationMemory
from agent_platform.memory.long_term import LongTermMemory, format_block
from agent_platform.models.base import ChatMessage
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.memories import MemoryRepository
from agent_platform.repositories.messages import MessageRepository
from agent_platform.repositories.projects import ProjectRepository
from agent_platform.services.settings_service import get_settings_service


class MemoryManager:
    def __init__(self, db: Session, model=None, *, enabled: bool | None = None) -> None:
        self.db = db
        self.model = model
        if enabled is None:
            enabled = bool(get_settings_service().load().get("memory_enabled", True))
        self.enabled = enabled
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)
        self.projects = ProjectRepository(db)
        self.convo_memory = ConversationMemory(model, self.messages, self.conversations)
        self.long_memory = LongTermMemory(model, MemoryRepository(db))

    async def build_messages(
        self, conversation: Conversation, entries: list[tuple[int, str, str]]
    ) -> tuple[list[ChatMessage], list[Event]]:
        """超长压缩 → 剔除已覆盖消息 → 注入全局/项目记忆 → 产出上下文与事件。"""
        events: list[Event] = []
        compressed = await self.convo_memory.ensure_summary(conversation, entries)
        if compressed:
            events.append(context_compressed(compressed))
        kept = self.convo_memory.recent_entries(conversation, entries)
        pairs = [(role, content) for _, role, content in kept]

        memory_block = ""
        if self.enabled and conversation.user_id:
            memories = self.long_memory.repo.list_for_context(conversation.user_id, conversation.project_id)
            if memories:
                project_name = ""
                if conversation.project_id:
                    project: Project | None = self.projects.get(conversation.project_id)
                    project_name = project.name if project else ""
                memory_block = format_block(memories, project_name=project_name)
        return build_context(pairs, summary=conversation.summary or "", memory_block=memory_block), events

    async def after_turn(self, conversation: Conversation, user_text: str, reply: str) -> list[Event]:
        """轮次结束后的记忆提炼（关闭自动记忆/无模型/空回复时静默跳过）。"""
        if not self.enabled or self.model is None or not reply.strip():
            return []
        saved = await self.long_memory.extract_and_save(
            conversation.user_id, conversation.project_id, user_text, reply
        )
        return [memory_saved(saved)] if saved else []

    def memory_block(self, user_id: int, project_id: int | None) -> str:
        """给任务执行器等非会话链路使用的记忆注入文本。"""
        if not self.enabled:
            return ""
        memories = self.long_memory.repo.list_for_context(user_id, project_id)
        if not memories:
            return ""
        project_name = ""
        if project_id:
            project = self.projects.get(project_id)
            project_name = project.name if project else ""
        return format_block(memories, project_name=project_name)
