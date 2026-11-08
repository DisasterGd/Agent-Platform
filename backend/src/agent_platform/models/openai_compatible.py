"""OpenAI 兼容接口实现（DeepSeek 等）。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from agent_platform.models.base import ChatMessage, ChatModel


class OpenAICompatibleModel:
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float) -> None:
        from openai import AsyncOpenAI  # 延迟导入：仅在真正调用模型时才需要

        self.model = model
        self.temperature = temperature
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    def _to_openai_messages(self, messages: list[ChatMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=self._to_openai_messages(messages),
            temperature=self.temperature,
            stream=True,
        )
        async for chunk in response:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content

    async def complete(self, messages: list[ChatMessage]) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=self._to_openai_messages(messages),
            temperature=self.temperature,
            stream=False,
        )
        content = response.choices[0].message.content
        return content or ""
