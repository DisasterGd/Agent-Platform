"""聊天业务用例：会话管理 + 流式回复。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from agent_platform.core.agent import Agent
from agent_platform.core.context import build_context
from agent_platform.core.events import (
    Event,
    error,
    task_completed,
    task_started,
    text_delta,
)
from agent_platform.infrastructure.database.models import Conversation
from agent_platform.models.factory import create_model
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.messages import MessageRepository


class ChatService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)
        self.model = create_model()

    def create_conversation(self, user_id: int, title: str = "新会话") -> Conversation:
        return self.conversations.create(user_id, title)

    def list_conversations(self, user_id: int) -> list[Conversation]:
        return self.conversations.list_by_user(user_id)

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        return self.conversations.get(conversation_id)

    def list_messages(self, conversation_id: int):
        return self.messages.list_by_conversation(conversation_id)

    async def stream_reply(self, conversation_id: int, content: str) -> AsyncIterator[Event]:
        yield task_started()

        # 先落库用户消息，再带着完整历史调用模型
        self.messages.add(conversation_id, "user", content)
        history = self.messages.list_by_conversation(conversation_id)
        chat_messages = build_context([(m.role, m.content) for m in history])

        parts: list[str] = []
        try:
            if self.model is not None:
                agent = Agent(self.model)
                async for token in agent.stream(chat_messages):
                    parts.append(token)
                    yield text_delta(token)
            else:
                async for token in self._demo_stream(content):
                    parts.append(token)
                    yield text_delta(token)
        except Exception as exc:  # noqa: BLE001
            yield error(f"模型调用失败：{exc}")
            return

        reply = "".join(parts).strip()
        if reply:
            self.messages.add(conversation_id, "assistant", reply)
        yield task_completed()

    async def _demo_stream(self, user_text: str) -> AsyncIterator[str]:
        reply = (
            f"我收到了你的消息：{user_text}\n\n"
            "当前未配置大模型 API Key，运行在本地演示模式。\n"
            "请在项目根目录的 .env 中填写 LLM_API_KEY（默认 DeepSeek）后重启后端，"
            "即可接入真实模型。"
        )
        for i in range(0, len(reply), 8):
            yield reply[i : i + 8]
            await asyncio.sleep(0.02)
