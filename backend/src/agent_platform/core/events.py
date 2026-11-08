"""统一事件定义。

Agent 核心、Service 与 API 层之间通过这些结构化事件传递流式输出。
SSE 编码只发生在 API 层，核心层不依赖 HTTP 细节。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


def text_delta(content: str) -> Event:
    return Event("text_delta", {"content": content})


def task_started() -> Event:
    return Event("task_started")


def task_completed() -> Event:
    return Event("task_completed")


def error(message: str) -> Event:
    return Event("error", {"message": message})


def to_sse(event: Event) -> str:
    """把事件编码为一条 SSE 帧（`data: {...}\n\n`）。"""
    return f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
