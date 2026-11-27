"""OpenAI 兼容接口实现（DeepSeek 等）。

v0.2 扩展：
- 支持图片（多模态）消息格式。
- 支持工具调用（function calling），包括流式与工具调用交织的场景。
v0.8 部署优化：AsyncOpenAI 客户端实例级复用——省掉每请求重建 HTTP 连接池/TLS 握手。
同一 (base_url, api_key) 共用一个客户端（不同用户 Key 不同，天然隔离）；无锁——dict 读写
在 GIL 下原子，竞态的最坏结果只是短暂多建一个客户端并被丢弃，无正确性影响。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from agent_platform.models.base import ChatMessage, ModelResponse, StreamEvent, ToolCall

_clients: dict[tuple[str, str], Any] = {}
_CLIENTS_MAX = 64


def _get_client(base_url: str, api_key: str) -> Any:
    from openai import AsyncOpenAI  # 延迟导入：仅在真正调用模型时才需要

    key = (base_url, api_key)
    client = _clients.get(key)
    if client is None:
        if len(_clients) >= _CLIENTS_MAX:
            _clients.pop(next(iter(_clients)))
        client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        _clients[key] = client
    return client


class OpenAICompatibleModel:
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float) -> None:
        self.model = model
        self.temperature = temperature
        self.client = _get_client(base_url, api_key)

    def _to_openai_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            item: dict[str, Any] = {"role": m.role}
            if m.images:
                parts: list[dict[str, Any]] = []
                if m.content:
                    parts.append({"type": "text", "text": m.content})
                parts.extend(
                    {"type": "image_url", "image_url": {"url": img.url}} for img in m.images
                )
                item["content"] = parts
            else:
                item["content"] = m.content
            if m.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            if m.tool_call_id:
                item["tool_call_id"] = m.tool_call_id
            if m.name:
                item["name"] = m.name
            out.append(item)
        return out

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

    async def complete_with_tools(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]]
    ) -> ModelResponse:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=self._to_openai_messages(messages),
            tools=tools,
            tool_choice="auto",
            temperature=self.temperature,
            stream=False,
        )
        msg = response.choices[0].message
        return ModelResponse(
            content=msg.content or "",
            tool_calls=self._parse_tool_calls(msg.tool_calls or []),
        )

    async def stream_with_tools(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]]
    ) -> AsyncIterator[StreamEvent]:
        """流式返回，同时识别工具调用。

        文本片段立即以 kind="text" 返回；当一次回复以工具调用结束（finish_reason=tool_calls）
        时，最后会以 kind="tool_calls" 返回一组完整解析好的 ToolCall。
        """
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=self._to_openai_messages(messages),
            tools=tools,
            tool_choice="auto",
            temperature=self.temperature,
            stream=True,
        )
        # index -> 累积的片段；arguments 分片到达，name 只出现在首个分片
        slots: dict[int, dict[str, str]] = {}
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not delta:
                continue
            if delta.content:
                yield StreamEvent(kind="text", text=delta.content)
            for tc in delta.tool_calls or []:
                slot = slots.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["arguments"] += tc.function.arguments

        if slots:
            yield StreamEvent(kind="tool_calls", tool_calls=self._finalize_tool_calls(slots))

    @staticmethod
    def _parse_tool_calls(raw: list[Any]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for tc in raw:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            calls.append(
                ToolCall(
                    id=getattr(tc, "id", "") or "",
                    name=fn.name or "",
                    arguments=OpenAICompatibleModel._parse_arguments(fn.arguments),
                )
            )
        return calls

    @staticmethod
    def _finalize_tool_calls(slots: dict[int, dict[str, str]]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for idx in sorted(slots):
            slot = slots[idx]
            calls.append(
                ToolCall(
                    id=slot["id"],
                    name=slot["name"],
                    arguments=OpenAICompatibleModel._parse_arguments(slot["arguments"]),
                )
            )
        return calls

    @staticmethod
    def _parse_arguments(raw: str) -> dict[str, Any]:
        raw = (raw or "").strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {"value": value}
        except (json.JSONDecodeError, ValueError):
            return {"_raw": raw}
