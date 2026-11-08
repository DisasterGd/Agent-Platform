"""对话上下文构建。"""
from __future__ import annotations

from agent_platform.models.base import ChatMessage

SYSTEM_PROMPT = "你是一个乐于助人的智能助手，请用简洁清晰的中文回答。"


def build_context(history: list[tuple[str, str]]) -> list[ChatMessage]:
    """把数据库中的 (role, content) 历史转换为发给模型的上下文。"""
    messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(ChatMessage(role=role, content=content) for role, content in history)
    return messages
