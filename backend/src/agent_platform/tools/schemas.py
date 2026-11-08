"""工具 JSON Schema 定义（v0.2 实现）。"""
from __future__ import annotations

from typing import Any


def tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }
