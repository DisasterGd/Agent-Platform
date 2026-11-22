"""Agent 核心执行入口。

v0.2 实现工具调用循环：
1. 把上下文与工具定义交给模型，流式输出。
2. 若模型请求调用工具，则执行工具，把结果回填到对话后再次请求模型。
3. 直到模型给出最终回答（或超过最大工具轮数）。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from agent_platform.core.events import (
    Event,
    artifact_ready,
    text_delta,
    tool_completed,
    tool_started,
)
from agent_platform.models.base import ChatMessage, ChatModel
from agent_platform.tools.registry import ToolRegistry


class Agent:
    MAX_TOOL_ROUNDS = 6

    def __init__(self, model: ChatModel, tools: ToolRegistry | None = None) -> None:
        self.model = model
        self.tools = tools

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[Event]:
        msgs = list(messages)
        tool_schemas = self.tools.schemas() if self.tools else []

        if not tool_schemas:
            async for token in self.model.stream(msgs):
                yield text_delta(token)
            return

        for _ in range(self.MAX_TOOL_ROUNDS):
            text_buf: list[str] = []
            tool_calls = []
            async for ev in self.model.stream_with_tools(msgs, tool_schemas):
                if ev.kind == "text":
                    text_buf.append(ev.text)
                    yield text_delta(ev.text)
                elif ev.kind == "tool_calls":
                    tool_calls = ev.tool_calls

            if not tool_calls:
                return

            # 回填 assistant 消息（含 tool_calls），随后逐个执行工具。
            msgs.append(
                ChatMessage(role="assistant", content="".join(text_buf), tool_calls=tool_calls)
            )
            for call in tool_calls:
                yield tool_started(call.name)
                try:
                    result = await self.tools.execute(call.name, call.arguments)
                except Exception as exc:  # noqa: BLE001
                    result = None
                    msgs.append(
                        ChatMessage(
                            role="tool",
                            content=json.dumps({"error": str(exc)}, ensure_ascii=False),
                            tool_call_id=call.id,
                            name=call.name,
                        )
                    )
                else:
                    for artifact in result.artifacts:
                        # 标记产出该文件的工具：服务层据此登记资料库条目（v0.5）
                        yield artifact_ready({**artifact, "tool": call.name})
                    msgs.append(
                        ChatMessage(
                            role="tool",
                            content=result.content,
                            tool_call_id=call.id,
                            name=call.name,
                        )
                    )
                yield tool_completed(call.name)

        # 工具轮数用尽仍无最终回答时，退化为普通流式回答。
        async for token in self.model.stream(msgs):
            yield text_delta(token)

    async def run(self, messages: list[ChatMessage]) -> str:
        parts: list[str] = []
        async for ev in self.stream(messages):
            if ev.type == "text_delta":
                parts.append(ev.data.get("content", ""))
        return "".join(parts)
