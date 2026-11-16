"""工具注册表与执行器（v0.2 工具调用）。

每个工具 = 名称 + 描述 + JSON Schema 参数 + 执行函数。
执行结果统一为 ToolResult：content 回传给模型，artifacts 用于向前端暴露生成的文件。
"""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_platform.tools.schemas import tool_schema


@dataclass
class ToolResult:
    """工具执行结果。content 为回传给模型的字符串（通常是 JSON）。"""

    content: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Awaitable[ToolResult] | ToolResult]

    def schema(self) -> dict[str, Any]:
        return tool_schema(self.name, self.description, self.parameters)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        fn: Callable[..., Awaitable[ToolResult] | ToolResult],
    ) -> None:
        self._tools[name] = Tool(name, description, parameters, fn)

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools[name]
        result = tool.fn(**arguments)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, ToolResult):
            return result
        # 兼容返回普通字符串的工具
        if isinstance(result, str):
            return ToolResult(content=result)
        return ToolResult(content=str(result))
