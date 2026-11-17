"""聊天业务用例：会话管理 + 流式回复（v0.2 工具调用，v0.3 附件）。"""
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
from agent_platform.infrastructure.attachments import (
    extract_text,
    image_to_data_uri,
    parse_file_url,
)
from agent_platform.infrastructure.database.models import Conversation
from agent_platform.models.base import ChatMessage, ImagePart
from agent_platform.models.factory import create_model, create_vision_model
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.messages import MessageRepository
from agent_platform.tools.builtin.registry import build_default_registry
from agent_platform.tools.registry import ToolRegistry

TITLE_SYSTEM_PROMPT = (
    "你是会话标题生成器。根据用户的问题，输出一个不超过 12 个汉字的中文标题，"
    "概括对话主题。只输出标题本身，不要引号、标点或任何解释。"
)

VISION_PROMPT = "请用简洁的中文描述这张图片的内容。"


class ChatService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)
        self.model = create_model()
        self.tools: ToolRegistry = build_default_registry()

    def create_conversation(self, user_id: int, title: str = "新会话") -> Conversation:
        return self.conversations.create(user_id, title)

    def list_conversations(self, user_id: int) -> list[Conversation]:
        return self.conversations.list_by_user(user_id)

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        return self.conversations.get(conversation_id)

    def list_messages(self, conversation_id: int):
        return self.messages.list_by_conversation(conversation_id)

    def rename_conversation(self, conversation_id: int, title: str) -> Conversation | None:
        title = title.strip()
        if not title:
            return self.conversations.get(conversation_id)
        return self.conversations.update_title(conversation_id, title)

    def update_conversation(
        self,
        conversation_id: int,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> Conversation | None:
        if title is not None:
            title = title.strip() or None
        return self.conversations.update(conversation_id, title=title, pinned=pinned)

    def delete_conversation(self, conversation_id: int) -> bool:
        return self.conversations.delete(conversation_id)

    async def regenerate_reply(
        self,
        conversation_id: int,
        message_id: int,
        new_content: str | None = None,
    ) -> AsyncIterator[Event]:
        """重新生成某条用户提问之后的回复（可选替换该提问内容）。"""
        target = self.messages.get(message_id)
        if target is None or target.conversation_id != conversation_id or target.role != "user":
            yield error("要重新生成的消息不存在或不是用户提问")
            return
        content = new_content.strip() if new_content is not None and new_content.strip() else target.content
        attachments = target.attachments or []
        # 删除该用户消息及其之后的所有消息，再按（可能编辑过的）内容重跑
        self.messages.delete_from(conversation_id, message_id)
        async for event in self.stream_reply(conversation_id, content, attachments):
            yield event

    async def _auto_title(self, conversation_id: int, content: str) -> None:
        """首条用户消息且标题仍为默认值时，用模型生成简洁标题（无模型则退化截断）。"""
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.title.strip() not in ("", "新会话"):
            return
        title = ""
        if self.model is not None:
            try:
                title = await self.model.complete(
                    [
                        ChatMessage(role="system", content=TITLE_SYSTEM_PROMPT),
                        ChatMessage(role="user", content=content),
                    ]
                )
            except Exception:  # noqa: BLE001 — 标题生成失败不影响主流程
                title = ""
        title = " ".join(title.split()).strip().strip('"\'“”「」『』')
        if not title:
            text = " ".join(content.split())
            title = text[:20] + ("…" if len(text) > 20 else "")
        self.conversations.update_title(conversation_id, title)

    async def _describe_image(self, category: str, stored_name: str, content_type: str) -> str | None:
        """用视觉模型描述图片；未配置视觉模型时返回 None。"""
        vision = create_vision_model()
        if vision is None:
            return None
        data_uri = image_to_data_uri(category, stored_name, content_type)
        if data_uri is None:
            return None
        try:
            return await vision.complete(
                [ChatMessage(role="user", content=VISION_PROMPT, images=[ImagePart(url=data_uri)])]
            )
        except Exception:  # noqa: BLE001 — 识图失败不影响主流程
            return None

    async def _enrich(self, content: str, attachments: list[dict]) -> str:
        """把附件正文/识图结果拼进用户消息，供模型读取。"""
        parts: list[str] = [content]
        for att in attachments:
            parsed = parse_file_url(att.get("url", ""))
            if parsed is None:
                continue
            category, stored_name = parsed
            content_type = att.get("content_type", "")
            name = att.get("name", stored_name)
            if content_type.startswith("image/"):
                description = await self._describe_image(category, stored_name, content_type)
                if description:
                    parts.append(f"\n\n[图片 {name}]\n{description}")
            else:
                text = extract_text(category, stored_name, content_type)
                if text:
                    parts.append(f"\n\n[附件 {name}]\n{text}")
        return "\n".join(parts)

    async def stream_reply(
        self,
        conversation_id: int,
        content: str,
        attachments: list[dict] | None = None,
    ) -> AsyncIterator[Event]:
        yield task_started()

        attachments = attachments or []
        enriched = await self._enrich(content, attachments)

        # 落库保存原始内容 + 附件元数据，供前端展示与刷新后回显
        self.messages.add(conversation_id, "user", content, attachments=attachments)
        self.conversations.touch(conversation_id)

        history = self.messages.list_by_conversation(conversation_id)
        pairs = [(m.role, m.content) for m in history]
        # 最后一条为刚插入的用户消息，用附带的文件正文/识图结果增强后发给模型
        if pairs and pairs[-1][0] == "user":
            pairs[-1] = ("user", enriched)
        chat_messages = build_context(pairs)

        parts: list[str] = []
        try:
            if self.model is not None:
                agent = Agent(self.model, tools=self.tools)
                async for event in agent.stream(chat_messages):
                    if event.type == "text_delta":
                        parts.append(event.data.get("content", ""))
                    yield event
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
        await self._auto_title(conversation_id, content)
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
