"""工具注册表（v0.2 实现工具调用）。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def get(self, name: str) -> Callable[..., Any]:
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())
