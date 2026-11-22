"""消息数据读写（含「重新生成」版本链）。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import Message


class MessageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        conversation_id: int,
        role: str,
        content: str,
        attachments: list | None = None,
        group_id: int | None = None,
        variant_index: int = 0,
    ) -> Message:
        """插入一条消息。

        group_id 为 None 时开启新链：首版 group_id 取自身 id（flush 后回填）。
        传入 group_id 时把新内容作为该链的下一个版本，不触碰旧版本。
        """
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            attachments=attachments,
            group_id=group_id,
            variant_index=variant_index if group_id is not None else 0,
        )
        self.db.add(message)
        self.db.flush()
        if message.group_id is None:
            message.group_id = message.id
        self.db.commit()
        self.db.refresh(message)
        return message

    def get(self, message_id: int) -> Message | None:
        return self.db.get(Message, message_id)

    def list_by_conversation(self, conversation_id: int) -> list[Message]:
        """全部消息（含每个版本链的所有变体），按时间/ID 排序，供前端分组展示。"""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return list(self.db.scalars(stmt))

    def list_active_by_conversation(self, conversation_id: int) -> list[Message]:
        """每个版本链只保留最新一版，顺序按各链首次出现的位置（用于构建模型上下文）。"""
        rows = self.list_by_conversation(conversation_id)
        order: list[int] = []
        best: dict[int, Message] = {}
        for m in rows:
            g = m.group_id or m.id
            if g not in best:
                order.append(g)
                best[g] = m
            else:
                cur = best[g]
                if (m.variant_index, m.id) >= (cur.variant_index, cur.id):
                    best[g] = m
        return [best[g] for g in order]

    def next_variant_index(self, group_id: int) -> int:
        """给定版本链的下一个 variant 序号。"""
        current = self.db.scalar(
            select(func.max(Message.variant_index)).where(Message.group_id == group_id)
        )
        return (current or 0) + 1

    def latest_snippet(self, conversation_id: int, width: int = 90) -> str:
        """会话“最近的相关信息”：取最新版本链中最后一条消息的正文摘要（搜索弹窗用）。"""
        rows = self.list_active_by_conversation(conversation_id)
        if not rows:
            return ""
        text = " ".join(rows[-1].content.split())
        return text[:width] + ("…" if len(text) > width else "")
