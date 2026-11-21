"""会话记忆（v0.4）：会话上下文自身 + 超长自动压缩。

定位是**临时记忆**：只在当前会话内有效，随会话删除而消失，不是跨会话知识。
当活跃历史超过配置阈值时，用模型的总结能力把早期消息滚动压缩为摘要
（conversations.summary），上下文 = 摘要 + 最近若干条原样消息。
核心层只依赖 ChatModel 协议与 Repository，不依赖 FastAPI。
"""
from __future__ import annotations

from agent_platform.config import settings
from agent_platform.infrastructure.database.models import Conversation
from agent_platform.models.base import ChatMessage
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.messages import MessageRepository

COMPRESS_SYSTEM_PROMPT = (
    "你是对话历史压缩器。把给定的早期对话消息合并进已有摘要（如有），"
    "输出一段不超过 400 字的中文摘要，保留：话题与结论、用户的目标与偏好线索、"
    "关键数据/文件名/URL、未完结的事项。直接输出摘要正文，不要任何前缀或解释。"
)


class ConversationMemory:
    def __init__(self, model, messages: MessageRepository, conversations: ConversationRepository) -> None:
        self.model = model
        self.messages = messages
        self.conversations = conversations

    def total_chars(self, entries: list[tuple[int, str, str]]) -> int:
        return sum(len(content) for _, _, content in entries)

    def recent_entries(self, conversation: Conversation, entries: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
        """剔除已被摘要覆盖的部分，返回应原样进入上下文的消息。"""
        covered = conversation.summary_covered_id or 0
        return [e for e in entries if e[0] > covered]

    async def ensure_summary(self, conversation: Conversation, entries: list[tuple[int, str, str]]) -> int:
        """未被摘要覆盖的历史超过阈值时，把它压缩到只剩最近 keep 条并落库摘要。

        返回本次新压缩的消息条数；无模型或无需压缩时返回 0（本地演示模式行为不变）。
        """
        if self.model is None:
            return 0
        covered = conversation.summary_covered_id or 0
        pending = [e for e in entries if e[0] > covered]
        keep = max(1, settings.context_keep_recent)
        if len(pending) <= keep:
            return 0
        if self.total_chars(pending) <= settings.context_compress_chars:
            return 0
        to_compress = pending[:-keep]
        if not to_compress:
            return 0
        lines = [f"{role}: {content[:800]}" for _, role, content in to_compress]
        prompt = "\n".join(lines)
        existing = (conversation.summary or "").strip()
        if existing:
            prompt = f"已有摘要：\n{existing[:1200]}\n\n需要并入的新对话：\n{prompt}"
        try:
            summary = await self.model.complete(
                [
                    ChatMessage(role="system", content=COMPRESS_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=prompt),
                ]
            )
        except Exception:  # noqa: BLE001 — 压缩失败不阻断对话，保持原样下次再试
            return 0
        summary = (summary or "").strip()
        if not summary:
            return 0
        self.conversations.update_summary(conversation.id, summary, to_compress[-1][0])
        conversation.summary = summary
        conversation.summary_covered_id = to_compress[-1][0]
        return len(to_compress)
