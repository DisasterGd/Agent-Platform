"""Agent 核心执行入口。

v0.1 只负责把上下文交给模型并流式返回；工具调用与任务规划将在后续版本加入。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from agent_platform.models.base import ChatMessage, ChatModel


class Agent:
    def __init__(self, model: ChatModel) -> None:
        self.model = model

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        async for token in self.model.stream(messages):
            yield token

    async def run(self, messages: list[ChatMessage]) -> str:
        return await self.model.complete(messages)
