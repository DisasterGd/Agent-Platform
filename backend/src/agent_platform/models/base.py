"""大模型适配层接口。

所有具体模型（OpenAI 兼容接口、其他）都实现 ChatModel 协议，
Agent 核心只依赖这个抽象，不关心具体供应商。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


class ChatModel(Protocol):
    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]: ...

    async def complete(self, messages: list[ChatMessage]) -> str: ...
