"""大模型适配层接口。

所有具体模型（OpenAI 兼容接口、其他供应商）都实现 ChatModel 协议，
Agent 核心只依赖这个抽象，不关心具体供应商。

v0.2 扩展：
- ChatMessage 支持图片（多模态），为后续多模态模型预留。
- 新增 ToolCall / StreamEvent / ModelResponse，用于工具调用（function calling）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ImagePart:
    """消息中的图片内容，url 可以是 http(s) 地址或 data URI。"""

    url: str


@dataclass
class ToolCall:
    """模型请求调用某个工具。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    images: list[ImagePart] = field(default_factory=list)
    # 工具调用回填字段（assistant 消息携带 tool_calls，tool 消息携带 tool_call_id/name）
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class StreamEvent:
    """流式返回的最小单元：文本片段或一次完整的工具调用请求。"""

    kind: str  # "text" | "tool_calls"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ModelResponse:
    """非流式返回：文本或工具调用。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]: ...

    async def complete(self, messages: list[ChatMessage]) -> str: ...

    async def complete_with_tools(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]]
    ) -> ModelResponse: ...

    async def stream_with_tools(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]]
    ) -> AsyncIterator[StreamEvent]: ...
